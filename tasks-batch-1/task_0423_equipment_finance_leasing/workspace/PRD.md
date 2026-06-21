# Equipment Finance & Leasing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Equipment Finance & Leasing API, the system of record for a commercial equipment lessor. A lessor underwrites credit for prospective lessees, originates and prices leases against vendor-supplied equipment, perfects its security interest through UCC-1 filings, administers sales/use and property tax, services monthly billing and collections, and manages the end-of-term disposition of leased assets — renewal, return, or buyout — including the remarketing of returned equipment.

The platform is built around two recurring tensions that pervade equipment finance. The first is **segregation of duties**: the analyst who submits a credit application must never be the one who approves or declines it, and the responsibilities of underwriting, funding, servicing, and asset remarketing are split across distinct operator roles. The second is **dual-dimension lease state**: a lease advances independently along a *lifecycle* axis (origination through booking, activation, end-of-term, and termination) and a *funding* axis (pending funding through funded), and certain milestones — most notably a lease becoming active — require both axes to align. Layered on top are the pricing peculiarities of three lease products (fair-market-value, one-dollar buyout, and terminal-rental-adjustment-clause leases), each with its own residual and buyout mathematics, and a logical clock that drives every temporal computation deterministically so that depreciation, UCC coverage windows, and serial-reuse buffers can be tested without wall-clock dependence.

This API is intended for back-office operators rather than end customers. Every monetary value is expressed in integer cents, every rate as basis points, and every time comparison reads a lessor-scoped logical clock rather than the host system time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles: `CreditAnalyst`, `FundingOfficer`, `Servicer`, and `AssetManager`. When a caller's role is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The four roles partition the workflow by duty. A `CreditAnalyst` underwrites credit applications — creating, submitting, returning for information, revising, approving, and declining them. A `FundingOfficer` onboards vendors, creates the lessor book of business, originates leases, books and funds them, attaches equipment, and manages UCC filings. A `Servicer` bills installments, records payments, voids invoices, generates property-tax assessments and remits tax, proposes and applies mid-term add-ons, and runs the end-of-term election process. An `AssetManager` handles remarketing of returned assets: marking units returned, listing them, recording sales, and disposing of them. All four roles may invoke any read (GET) endpoint. Setting the logical clock is shared between `FundingOfficer` and `Servicer`.

For every role, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity. The server does not compare it to any entity's `id`. It does, however, record it where a workflow demands it: when a `CreditAnalyst` submits a credit application, the server stamps that analyst's `X-User-ID` onto the application's `submitted_by_user_id` field, and the segregation-of-duties rule later compares the approving or declining analyst's `X-User-ID` against that recorded value. This recording is the sole use of `X-User-ID`; it is never matched against a resource's own `id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every primary resource carries a system-generated `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 (or its initial server-assigned value) and increments by one on every mutation. Whenever a derived or computed field changes as part of a workflow — for instance, when a lessee's committed credit is recomputed or a lessor's portfolio value is refreshed — that change is itself a mutation that advances `updated_at` and `version` on the affected resource.

All entities in this system maintain the full set of common fields (`id`, `created_at`, `updated_at`, `version`); there are no append-only or immutable sub-resources that omit `updated_at` or `version`.

### 2.5. Hierarchical Consistency and Cascade Propagation

Many operations in this system mutate more than one resource. When such a cascade fires, every affected entity is updated as an immediate, synchronous part of the same operation — the system never defers a dependent recomputation. The most pervasive cascades concern credit and portfolio aggregates. A lessee's `committed_credit_cents` is the sum of `financed_amount_cents` over that lessee's leases whose `lifecycle_status` is `ORIGINATION`, `BOOKED`, `ACTIVE`, or `END_OF_TERM`, and its `available_credit_cents` is `approved_credit_cents` minus `committed_credit_cents`; whenever a lease enters or leaves that set, or its financed amount changes, both figures are recomputed. A lessor's `portfolio_value_cents` is the sum of `original_cost_cents` over every equipment unit whose owning lease is in `BOOKED`, `ACTIVE`, or `END_OF_TERM`; it is recomputed whenever a unit is added, a lease's lifecycle changes, or a unit's disposition changes its membership in that set. Each such recomputation independently mutates its resource, advancing that resource's `updated_at` and `version`.

### 2.6. Nested Resource Retrieval and Path Validation

Resource paths are validated left to right. When a path names several resources — for example a lessor, then a lease beneath it, then an equipment unit beneath that — the system confirms the existence of each identifier in order and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve. A request naming a real lessor but a non-existent lease fails on the lease before any deeper resource is consulted. This ordering holds for reads, writes, and transition endpoints alike.

### 2.7. Monetary Values, Rates, and Rounding

All amounts are stored and returned as integer cents; all rates are stored as integer basis points, where one percent equals 100 basis points (so a rate of 825 basis points means 8.25%). Wherever a calculation multiplies an amount by a basis-point rate, the system divides the product by 10,000 and rounds the result to the nearest whole cent using the **round half up** convention — a result whose fractional part is exactly one-half rounds up. Each individual calculation specifies precisely where this rounding occurs; per-line tax in particular is rounded on each invoice independently and is never derived by rounding a summed total. Subtractions of already-integer amounts (such as financed amount) involve no rounding.

### 2.8. The Logical Clock

Each lessor owns a logical clock, `clock_utc`, which is the single source of truth for every temporal comparison the system makes: lease booking timestamps, installment due dates, equipment depreciation, UCC coverage windows, and serial-reuse buffers all read this clock rather than the host wall clock. The clock is initialized when a lessor is created and advances only when an operator explicitly sets it via the clock-set capability, supplying the target instant as `to_iso8601`. Because all time-dependent logic reads `clock_utc`, advancing the clock is how the passage of time is simulated deterministically.

### 2.9. Optimistic Concurrency Control on Booking

Booking a lease is the one operation guarded by optimistic concurrency control. A booking request must carry `expected_lease_version`, and the server compares it to the target lease's current `version`. If they do not match — meaning the lease's version has advanced since the client last read it, perhaps because a competing add-on or a prior book attempt against the same lessee already changed the credit exposure — the booking is rejected with `ERR_STALE_VERSION` and HTTP status 412. This prevents a client from committing credit against a lease state it has not observed, which could otherwise double-count exposure. No other endpoint accepts or requires a version field; only booking carries this check.

### 2.10. Segregation of Duties

Underwriting authority is deliberately split. When a credit application is submitted, the submitting analyst's identity is captured in `submitted_by_user_id`. At approval and at decline, the system requires that the acting analyst's `X-User-ID` differ from `submitted_by_user_id`; if the same analyst attempts to approve or decline an application they themselves submitted, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). When an application is revised back to draft, `submitted_by_user_id` is cleared so that a fresh submission must re-stamp the submitter, keeping the rule meaningful across revision cycles.

### 2.11. Validation Ordering

Across all endpoints, validations are applied in a fixed priority order so that the same request always fails on the same, most-fundamental cause. The order is: first, user-context header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); third, existence of every path-referenced resource validated left to right (`ERR_NOT_FOUND`); fourth, request-body well-formedness — required fields present, enumerations valid, and amounts strictly positive where required (`ERR_INVALID_REQUEST`); fifth, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); and sixth, on booking specifically, the optimistic-concurrency version check (`ERR_STALE_VERSION`). Only after all of these pass does the system evaluate the operation-specific business rules described in Section 3. Within those business rules, where a single endpoint carries several checks, the more specific orderings are called out in the relevant workflow narrative.

## 3. Business Logic & Workflows

### 3.1. Establishing the Book of Business: Lessors and Vendors

Everything begins with a **Lessor**, the legal entity that owns the leasing book. A `FundingOfficer` creates a lessor by supplying its `legal_name`, its `home_state_code` (the two-letter US state of its filing office), its `sales_tax_rate_bps`, and its `property_tax_rate_bps`. On creation the lessor's logical clock is initialized and its `portfolio_value_cents` starts at zero. The lessor also exposes `clock_utc`, which operators may advance as described in Section 2.8.

Vendors supply the equipment that leases finance. A `FundingOfficer` registers a **Vendor** under a lessor with a `name` and a `remit_account` (the funding remittance reference); the vendor begins in `PENDING` status. Only an `APPROVED` vendor may receive funding, so a vendor must be moved from `PENDING` to `APPROVED` before any lease that names it can be funded. An approved vendor may later be moved to `SUSPENDED`, and a suspended vendor may be returned to `APPROVED`; these toggles are performed by a `FundingOfficer`. The vendor's `status` and its `lessor_id` association are system-managed.

### 3.2. Underwriting: The Credit Application Lifecycle

A `CreditAnalyst` opens a **Credit Application** by providing the prospective lessee's `applicant_legal_name`, the `requested_amount_cents` they are seeking, and the applicant's bureau `credit_score`. The application is born in `DRAFT` with `revision_count` at zero. Its `approved_amount_cents` and `pricing_tier` are not yet set, and `submitted_by_user_id` is empty.

The application moves through a small state machine. From `DRAFT`, submitting it advances it to `SUBMITTED`; submission requires `requested_amount_cents` to be greater than zero and `credit_score` to fall within the inclusive range 300 through 850, failing which the request is rejected with `ERR_INVALID_REQUEST`. On a successful submission the system stamps the submitting analyst's `X-User-ID` into `submitted_by_user_id`. From `SUBMITTED`, an analyst may return the application for more information, advancing it to `RETURNED_FOR_INFO`. From `RETURNED_FOR_INFO`, revising it returns it to `DRAFT`; revision increments `revision_count` by one and clears `submitted_by_user_id` back to empty, so the next submission re-stamps a fresh submitter. This `RETURNED_FOR_INFO → DRAFT → SUBMITTED` loop may repeat any number of times.

From `SUBMITTED`, the application resolves either to `APPROVED` or to `DECLINED`, and both are terminal. Approval and decline are both subject to segregation of duties (Section 2.10): the acting analyst's `X-User-ID` must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Approval carries two further checks evaluated after the segregation check: the supplied `approved_amount_cents` must be greater than zero and must not exceed `requested_amount_cents` (otherwise `ERR_APPROVED_EXCEEDS_REQUESTED`), and the application's `credit_score` must be at least 580 (otherwise `ERR_SCORE_BELOW_FLOOR`). When approval succeeds, the system records `approved_amount_cents` from the request, computes `pricing_tier`, and — as a cross-entity side effect — mints a **Lessee** bound to this application. Decline, by contrast, carries only the segregation-of-duties check and simply marks the application `DECLINED` with no further side effects.

The `pricing_tier` is derived from `credit_score` at approval time by thresholds: a score of at least 720 yields `PRIME`; a score from 640 up to but not including 720 yields `NEAR_PRIME`; and a score below 640 (necessarily in the 580-through-639 band, since lower scores are rejected by the underwriting floor) yields `SUBPRIME`.

### 3.3. The Lessee and the Credit Envelope

Approving an application mints a **Lessee**, the borrowing counterparty. The lessee's `credit_application_id` records the approved application that minted it, its `legal_name` is copied from the application's `applicant_legal_name`, and its `approved_credit_cents` is copied from the application's `approved_amount_cents` at mint time. Its `lessor_id` ties it to the book. Two figures track utilization of the envelope: `committed_credit_cents`, the sum of `financed_amount_cents` across this lessee's leases in lifecycle `ORIGINATION`, `BOOKED`, `ACTIVE`, or `END_OF_TERM`; and `available_credit_cents`, equal to `approved_credit_cents` minus `committed_credit_cents`. Both begin effectively at zero committed and full availability and are recomputed by the cascades of Section 2.5 whenever a lease's financed amount or lifecycle membership changes. Lessees are read individually or listed, and the list may be filtered by `credit_application_id` to reverse-look-up the lessee a given application produced.

### 3.4. Originating and Booking a Lease

A `FundingOfficer` originates a **Lease** under a lessee. At creation the officer supplies the funding `vendor_id`, the `lease_type` (one of `FMV`, `DOLLAR_OUT`, or `TRAC`), the `equipment_cost_cents` (the vendor invoice cost, which must be positive), the `term_months` (a positive count of monthly payments), and the `monthly_rate_factor_bps` (the lease rate factor in basis points of equipment cost charged per month). Three optional inputs may accompany origination: `trac_residual_pct_bps`, the stipulated TRAC residual in basis points of cost; `advance_payment_count`, the number of monthly payments collected up front (defaulting to zero); and `security_deposit_cents`, a refundable deposit collected at booking (defaulting to zero). A freshly created lease sits in `lifecycle_status` `ORIGINATION` and `funding_status` `PENDING_FUNDING`; these two dimensions advance independently. Its system-managed `lessee_id` records the lessee it was originated under. Its computed fields — `financed_amount_cents`, `monthly_payment_cents`, `residual_value_cents`, `paid_installment_count` — and its `booked_clock_utc` are not yet meaningful. The lease list may be filtered by `lessee_id`, by `vendor_id`, by `lifecycle_status`, or by `funding_status`.

Before booking, the officer attaches at least one equipment unit (Section 3.5). **Booking** drives the lease from `ORIGINATION` to `BOOKED` and is the system's pricing moment. The request supplies `expected_lease_version` for the optimistic-concurrency check of Section 2.9. Booking enforces a sequence of preconditions: the version check first (`ERR_STALE_VERSION`, 412); then the cross-entity credit check that the lessee's `available_credit_cents` is at least the lease's computed `financed_amount_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`); that at least one `EquipmentUnit` is attached (`ERR_NO_EQUIPMENT`); and the TRAC consistency rule — `trac_residual_pct_bps` must be present exactly when `lease_type` is `TRAC` and absent otherwise, and when present it must be at least 1000 basis points, i.e. at least 10% of cost (`ERR_TRAC_RESIDUAL_REQUIRED`).

A successful booking performs a rich set of side effects. The lifecycle becomes `BOOKED`. The lease's `booked_clock_utc` is captured from the lessor's current `clock_utc`; depreciation later measures months in service from this instant. The pricing fields are computed in a pinned order. First, `monthly_payment_cents` is set to the equipment cost multiplied by the monthly rate factor in basis points, divided by 10,000, rounded half up — this is the base scheduled rent before tax. Next, `financed_amount_cents`, the credit exposure, is the equipment cost minus the product of `advance_payment_count` and the just-computed monthly payment, minus the security deposit; because all three terms are integers this subtraction is exact. Then `residual_value_cents` is computed by lease type (Section 3.6). Booking also generates the installment schedule: exactly `term_months` **Schedule Line** rows are created, the first `advance_payment_count` of which are marked `is_advance` true with status `WAIVED` (they were collected up front), and the remainder with status `SCHEDULED`. Finally, booking increments the lease's `version` by one and triggers the credit and portfolio cascades of Section 2.5, recomputing the lessee's committed and available credit and the lessor's portfolio value.

Each schedule line records its `lease_id`, a 1-based `installment_number`, a `due_clock_utc` equal to the booking clock plus `installment_number` months, a `base_rent_cents` equal to the lease's monthly payment, the `is_advance` flag, and its `status` (`SCHEDULED`, `INVOICED`, `PAID`, or `WAIVED`).

### 3.5. Attaching Equipment and Serial Discipline

A `FundingOfficer` attaches an **Equipment Unit** to a lease by supplying its `serial_number`, a `description`, and its `original_cost_cents` (a positive capitalized cost). A new unit enters in status `ON_LEASE`. The system also tracks each unit's computed `assessed_value_cents` (its depreciated value for property tax), its `disposed_clock_utc` (set when it reaches `DISPOSED`), and its `sale_proceeds_cents` (recorded when a listed unit is sold).

Serial numbers are policed in two ways. First, a serial must be unique per lessor across all non-`DISPOSED` units at the instant of attachment; attaching a unit whose serial is already held by a live (non-disposed) unit is rejected with `ERR_DUPLICATE_SERIAL`. Second, even when no live unit currently holds the serial, a recently retired serial is quarantined: if some unit bearing the same serial was disposed at clock instant D, reuse is blocked while the lessor's current `clock_utc` is less than or equal to D plus the buffer of 30 days — the buffer window is closed at both ends, so reuse is permitted only strictly after D plus 30 days. When several disposed units shared the serial, D is taken from the most recent disposal. A reuse inside the window is rejected with `ERR_SERIAL_REUSE_TOO_SOON`, and this temporal check is evaluated only after the instantaneous duplicate check has confirmed no live unit holds the serial. Both checks apply when attaching equipment directly and when an add-on creates a new unit.

### 3.6. Lease Pricing by Product Type

The three lease products price their residuals differently, and `residual_value_cents` is set at booking accordingly. For a `DOLLAR_OUT` lease the residual is a fixed nominal $1, that is, exactly 100 cents, regardless of term or cost. For an `FMV` lease the residual is a fair-market band on `equipment_cost_cents`, tiered by `term_months`: a term of 24 months or fewer uses a band of 2000 basis points (20%); a term greater than 24 but no more than 48 months uses 1500 basis points (15%); and a term greater than 48 months uses 1000 basis points (10%). The chosen band is multiplied by the equipment cost, divided by 10,000, and rounded half up. For a `TRAC` lease the residual is the client-stipulated `trac_residual_pct_bps` multiplied by the equipment cost, divided by 10,000, rounded half up; as noted in Section 3.4 the stipulated figure must be at least the TRAC floor of 1000 basis points.

### 3.7. Funding the Vendor, Filing UCC, and Activation

The funding axis advances independently of lifecycle. A `FundingOfficer` **funds** a lease, moving its `funding_status` from `PENDING_FUNDING` to `FUNDED`. Funding requires the lease to already be in lifecycle `BOOKED` (otherwise `ERR_NOT_BOOKED`) and the lease's vendor to be in `APPROVED` status (otherwise `ERR_VENDOR_NOT_APPROVED`). Funding triggers a three-deep cascade. First the system creates a **UCC Filing** in `PENDING` and immediately auto-files it, moving it to `FILED`: it assigns a `filing_number`, sets `filed_clock_utc` to the lessor's current clock, and sets `coverage_end_clock_utc` to the filed instant plus 60 months. Then it generates a `SALES_USE` **Tax Assessment** whose taxable base feeds the lessor's tax liability. Finally, because funding completes the second of the two conditions for activation, the system performs the automatic lifecycle transition described next.

A lease reaches `ACTIVE` only when **both** dimensions align: its `lifecycle_status` is `BOOKED` and its `funding_status` is `FUNDED`. This `BOOKED → ACTIVE` transition is performed automatically by the system at the moment funding completes — there is no separate operator action for it. The lease's `lifecycle_status` becomes `ACTIVE`.

A UCC filing carries its `lease_id`, its `jurisdiction_state_code`, the assigned `filing_number`, the `filed_clock_utc`, the computed `coverage_end_clock_utc`, and its `status` (`PENDING`, `FILED`, `LAPSED`, or `TERMINATED`). Beyond the automatic filing created at funding, a `FundingOfficer` may **manually file** a continuation against a lease by supplying a `jurisdiction_state_code`, which must equal the lessor's `home_state_code` (otherwise `ERR_UCC_WRONG_JURISDICTION`). A manual filing's coverage window is half-open: it runs from `filed_clock_utc` (inclusive) up to `coverage_end_clock_utc` (exclusive), where the end is the filed instant plus the 60-month lapse period. A new filing for the same lease and jurisdiction is rejected with `ERR_UCC_OVERLAP` if the lessor's current clock falls inside the half-open coverage window of an existing `FILED` filing for that same lease and jurisdiction — that is, at or after that filing's filed instant and strictly before its coverage end. A filing whose coverage end is at or before the current clock has `LAPSED` and no longer occupies its interval; because the window is half-open, a continuation filed exactly at the prior filing's coverage-end instant is accepted. Lapse is a system transition from `FILED` to `LAPSED` that the system evaluates on read and whenever a new filing's overlap is checked. A `FundingOfficer` may also terminate a `FILED` filing, moving it to `TERMINATED`; a terminated window likewise frees the interval.

### 3.8. Tax Administration

Two kinds of **Tax Assessment** exist, distinguished by `tax_type` (`SALES_USE` or `PROPERTY`), each recording its `lease_id`, an `assessment_clock_utc` capturing when it was generated, a computed `taxable_base_cents`, a computed `tax_amount_cents`, and a `status` of `ASSESSED` or `REMITTED`. A `SALES_USE` assessment is generated automatically when a lease is funded; a `PROPERTY` assessment is generated on demand by a `Servicer`.

The two types compute their base and amount differently. For a `SALES_USE` assessment, the taxable base is the lease's `equipment_cost_cents`, and the tax amount is that base multiplied by the lessor's `sales_tax_rate_bps`, divided by 10,000, rounded half up. For a `PROPERTY` assessment, the taxable base is the sum of `assessed_value_cents` over the lease's units whose status is not `DISPOSED`, and the tax amount is that base multiplied by the lessor's `property_tax_rate_bps`, divided by 10,000, rounded half up.

A unit's `assessed_value_cents` follows straight-line annual depreciation with a floor. The system measures `months_in_service` as the whole months between the lease's `booked_clock_utc` and the lessor's current `clock_utc` (never negative; zero if the lease is not yet booked), then takes `years_in_service` as that month count divided by twelve and rounded down to a whole number. The depreciated value is the unit's `original_cost_cents` minus the result of multiplying that original cost by ten percent per year in service, that product being rounded half up. A floor equal to twenty percent of original cost, rounded half up, is then applied: the assessed value is the larger of the depreciated value and the floor. The floor is applied after depreciation.

A `Servicer` may mark an assessment `REMITTED` once it has been settled.

### 3.9. Billing, Payments, and Installment Settlement

Servicing turns scheduled rent into cash. A `Servicer` **bills** a scheduled installment by creating an **Invoice** for a lease, supplying the `schedule_line_id` of the installment to bill. The invoice records its `lease_id`, the `schedule_line_id`, a `base_rent_cents` copied from the schedule line's base rent at invoice time, a computed `sales_tax_cents`, a computed `total_due_cents`, an `amount_paid_cents` (starting at zero), and a `status` of `OPEN`, `PAID`, or `VOID`. Billing moves the underlying schedule line to `INVOICED`. The per-invoice sales tax is the invoice's own base rent multiplied by the lessor's `sales_tax_rate_bps`, divided by 10,000, rounded half up; the total due is the base rent plus that tax. This rounding happens per invoice — each invoice's tax is rounded on its own base rent and never by summing several base rents and taxing the total, so two equal rents of $33.33 at 8.25% each round to 275 cents independently.

A `Servicer` records a **Payment** against an invoice by supplying `amount_cents`, which must be positive and must not exceed the invoice's outstanding balance — its `total_due_cents` minus its `amount_paid_cents` — at apply time, else `ERR_PAYMENT_EXCEEDS_DUE`. A payment records its `invoice_id`, a denormalized `lease_id` for lease-scoped lookups, the `amount_cents`, and a `status` of `CLEARED` or `REVERSED`; payments clear immediately. Each cleared payment adds its amount to the invoice's `amount_paid_cents`, which is the sum of `amount_cents` over the invoice's cleared payments. When `amount_paid_cents` reaches or exceeds `total_due_cents`, the system automatically moves the invoice from `OPEN` to `PAID`; this cascades to set the linked schedule line's status to `PAID`, and the lease's `paid_installment_count` — the count of its schedule lines in `PAID` status — is recomputed.

A `Servicer` may **void** an `OPEN` invoice, but only when it has no cleared payments, that is `amount_paid_cents` equals zero (otherwise `ERR_INVOICE_HAS_PAYMENTS`). Voiding moves the invoice to `VOID` and cascades the linked schedule line's status back to `SCHEDULED`, making it billable again.

### 3.10. Mid-Term Changes: Add-Ons and Upgrades

During the active life of a lease, a `Servicer` may propose an **Add-On** to finance additional or replacement equipment. The proposal supplies a `kind` (`ADD_ON` or `UPGRADE`), the `added_cost_cents` (a positive capitalized cost), and, because applying it will create a new equipment unit, that unit's `serial_number` and `description`. For an `UPGRADE`, the proposal must also supply `replaces_equipment_unit_id` identifying the unit being replaced; for an `ADD_ON` that field must be absent. The add-on records its `lease_id`, its computed `incremental_payment_cents`, and a `status` of `PROPOSED`, `APPLIED`, or `REJECTED`. A `Servicer` may reject a proposed add-on, moving it to `REJECTED`.

**Applying** an add-on moves it from `PROPOSED` to `APPLIED` and is gated by three checks: the owning lease must be in `lifecycle_status` `ACTIVE` (otherwise `ERR_LEASE_NOT_ACTIVE`); the lessee's `available_credit_cents` must be at least `added_cost_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`); and for an `UPGRADE`, `replaces_equipment_unit_id` must reference a unit on this lease whose status is `ON_LEASE` (otherwise `ERR_INVALID_REQUEST`). The incremental monthly rent, `incremental_payment_cents`, is the added cost multiplied by the lease's `monthly_rate_factor_bps`, divided by 10,000, rounded half up — but only when there is at least one remaining `SCHEDULED` schedule line to spread it over; when no `SCHEDULED` installments remain, the incremental payment is zero because there is nothing left to charge it against.

Application triggers a three-deep cascade. The `base_rent_cents` of every remaining `SCHEDULED` schedule line is increased by the incremental payment; the lease's `financed_amount_cents` is increased by `added_cost_cents`; and that in turn recomputes the lessee's committed and available credit and the lessor's portfolio value per Section 2.5. Application also creates a new equipment unit in `ON_LEASE` for the added equipment (subject to the serial discipline of Section 3.5), and for an `UPGRADE`, the replaced unit's status is set to `DISPOSED`.

### 3.11. End of Term: Election, Exercise, and Termination

A lease reaches the end-of-term phase when a `Servicer` **begins end-of-term**, moving its `lifecycle_status` from `ACTIVE` to `END_OF_TERM`. This is permitted only once the scheduled term is fully paid: `paid_installment_count` must be at least `term_months` minus `advance_payment_count` (otherwise `ERR_TERM_NOT_COMPLETE`), reflecting that the advance installments were collected and waived up front rather than billed.

Within end-of-term, a `Servicer` records an **End-Of-Term Election** for the lease, supplying the `election` (`RENEW`, `RETURN`, or `BUYOUT`) and, for a renewal, `renewal_months` (a positive extension term, required for `RENEW` and forbidden otherwise). The election records its `lease_id`, a computed `quoted_amount_cents`, and a `status` of `ELECTED`, `EXERCISED`, or `CANCELLED`. The quoted amount depends on the election: for `RETURN` it is zero; for `RENEW` it is the renewal monthly rent; and for `BUYOUT` it is the buyout price computed by product type. The buyout price first determines the remaining installments as `term_months` minus `paid_installment_count` minus `advance_payment_count`, floored at zero, and the remaining rent as that count multiplied by the lease's `monthly_payment_cents`. Then: a `DOLLAR_OUT` buyout is a fixed 100 cents; an `FMV` buyout is the lease's `residual_value_cents` plus the remaining rent (the lessee buys at fair value); and a `TRAC` buyout is the `residual_value_cents` alone, since a TRAC lease adjusts at sale rather than at buyout.

A `Servicer` **exercises** an elected option, moving it from `ELECTED` to `EXERCISED`. Exercise requires the lease to be in `lifecycle_status` `END_OF_TERM` (otherwise `ERR_LEASE_NOT_END_OF_TERM`), and for a `BUYOUT` election it requires the request to carry `buyout_payment_cents` equal to the election's `quoted_amount_cents` (otherwise `ERR_BUYOUT_NOT_PAID`). Exercising a `RENEW` appends `renewal_months` new schedule lines and increases the lease's `term_months` by `renewal_months`. Exercising a `BUYOUT` sets every equipment unit on the lease to `SOLD`, splitting `quoted_amount_cents` across the units as `sale_proceeds_cents` by integer division, with any remainder assigned to the unit having the earliest `created_at`. A `Servicer` may instead **cancel** an elected option, moving it to `CANCELLED`.

Finally, a `Servicer` **terminates** an end-of-term lease, moving its `lifecycle_status` from `END_OF_TERM` to `TERMINATED` (a terminal state). Termination requires that some end-of-term election for the lease be in `EXERCISED` status (otherwise `ERR_ELECTION_NOT_EXERCISED`) and that no invoice for the lease be `OPEN` with a positive outstanding balance — that is, with `total_due_cents` greater than `amount_paid_cents` (otherwise `ERR_OUTSTANDING_BALANCE`). Termination records the security-deposit refund obligation, then runs the credit and portfolio cascades of Section 2.5 as the lease drops out of the committed-credit set and out of the active portfolio.

### 3.12. Remarketing Returned Equipment

When a lease ends by return, an `AssetManager` takes over the asset. A unit is **returned** — moved from `ON_LEASE` to `RETURNED` — only when its owning lease is in `lifecycle_status` `END_OF_TERM` (otherwise `ERR_LEASE_NOT_END_OF_TERM`) and that lease's end-of-term election is `RETURN` and in `EXERCISED` status (otherwise `ERR_ELECTION_MISMATCH`). From `RETURNED`, the manager may **list** the unit for sale, moving it to `LISTED`, or **dispose** of it, moving it to `DISPOSED`.

Selling a listed unit — a `record-sale` action — moves it from `LISTED` to `SOLD`. The request carries `sale_proceeds_cents`, which must be at least zero (otherwise `ERR_INVALID_REQUEST`); the system records those proceeds on the unit and computes the remarketing gain or loss as `sale_proceeds_cents` minus the owning lease's `residual_value_cents` — a positive figure being a gain and a negative one a loss — against the residual booked at origination. The sale also recomputes the lessor's portfolio value, since the unit leaves the active book if its lease has terminated. A `LISTED` unit may instead be disposed, moving it to `DISPOSED`. Whenever a unit reaches `DISPOSED` — whether from `RETURNED` or from `LISTED` — its `disposed_clock_utc` is set to the lessor's current clock, which starts the 30-day serial-reuse buffer window of Section 3.5. The terminal states for an equipment unit are `SOLD` and `DISPOSED`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`; operations that modify an existing resource — including all state-transition actions and clock setting — return `200 OK`. Every path is rooted at the lessor identified by `lessorId`; the table below lists the path suffix after the API host. Request and response bodies are not repeated here; reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lessors` | Create a Lessor (book of business) | FundingOfficer |
| GET | `/lessors/{lessorId}` | Get a Lessor | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/_clock/set` | Set the Lessor logical clock | FundingOfficer, Servicer |
| POST | `/lessors/{lessorId}/vendors` | Create a Vendor | FundingOfficer |
| GET | `/lessors/{lessorId}/vendors/{id}` | Get a Vendor | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/vendors` | List Vendors for a Lessor | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/vendors/{id}/approve` | Approve a Vendor for funding | FundingOfficer |
| POST | `/lessors/{lessorId}/vendors/{id}/suspend` | Suspend an approved Vendor | FundingOfficer |
| POST | `/lessors/{lessorId}/credit-applications` | Create a credit application (DRAFT) | CreditAnalyst |
| GET | `/lessors/{lessorId}/credit-applications/{id}` | Get a credit application | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/credit-applications` | List credit applications for a Lessor | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/credit-applications/{id}/submit` | Submit a DRAFT application for review | CreditAnalyst |
| POST | `/lessors/{lessorId}/credit-applications/{id}/return-for-info` | Return a SUBMITTED application for more information | CreditAnalyst |
| POST | `/lessors/{lessorId}/credit-applications/{id}/revise` | Return a RETURNED_FOR_INFO application to DRAFT | CreditAnalyst |
| POST | `/lessors/{lessorId}/credit-applications/{id}/approve` | Approve a SUBMITTED application; mints a Lessee | CreditAnalyst |
| POST | `/lessors/{lessorId}/credit-applications/{id}/decline` | Decline a SUBMITTED application | CreditAnalyst |
| GET | `/lessors/{lessorId}/lessees/{id}` | Get a Lessee | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/lessees` | List Lessees (filter by credit_application_id) | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/lessees/{id}/leases` | Create a Lease (ORIGINATION / PENDING_FUNDING) | FundingOfficer |
| GET | `/lessors/{lessorId}/leases/{id}` | Get a Lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases` | List Leases for a Lessor | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/leases/{id}/book` | Book a lease (OCC on lease version) | FundingOfficer |
| POST | `/lessors/{lessorId}/leases/{id}/fund` | Fund the vendor; file UCC; generate sales/use tax; activate | FundingOfficer |
| POST | `/lessors/{lessorId}/leases/{id}/begin-end-of-term` | Move an ACTIVE lease into END_OF_TERM | Servicer |
| POST | `/lessors/{lessorId}/leases/{id}/terminate` | Terminate an END_OF_TERM lease | Servicer |
| POST | `/lessors/{lessorId}/leases/{id}/equipment` | Attach an EquipmentUnit to a lease | FundingOfficer |
| GET | `/lessors/{lessorId}/equipment/{id}` | Get an EquipmentUnit | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/equipment` | List EquipmentUnits on a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/equipment/{id}/return` | Mark a returned unit | AssetManager |
| POST | `/lessors/{lessorId}/equipment/{id}/list` | List a returned unit for remarketing | AssetManager |
| POST | `/lessors/{lessorId}/equipment/{id}/record-sale` | Record sale of a listed unit | AssetManager |
| POST | `/lessors/{lessorId}/equipment/{id}/dispose` | Dispose a returned or listed unit | AssetManager |
| GET | `/lessors/{lessorId}/schedule-lines/{id}` | Get a ScheduleLine | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/schedule-lines` | List ScheduleLines for a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/schedule-lines/{id}/invoices` | List Invoices billing this ScheduleLine | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/leases/{id}/invoices` | Bill a SCHEDULED installment | Servicer |
| GET | `/lessors/{lessorId}/invoices/{id}` | Get an Invoice | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/invoices` | List Invoices for a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/invoices/{id}/void` | Void an unpaid Invoice | Servicer |
| POST | `/lessors/{lessorId}/invoices/{id}/payments` | Record a payment against an invoice | Servicer |
| GET | `/lessors/{lessorId}/payments/{id}` | Get a Payment | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/invoices/{id}/payments` | List Payments for an invoice | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/payments` | List Payments for a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/leases/{id}/ucc-filings` | Manually file a UCC-1 continuation | FundingOfficer |
| GET | `/lessors/{lessorId}/ucc-filings/{id}` | Get a UCC filing | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/ucc-filings` | List UCC filings for a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/ucc-filings/{id}/terminate` | Terminate a FILED UCC filing | FundingOfficer |
| POST | `/lessors/{lessorId}/leases/{id}/tax-assessments` | Generate a PROPERTY tax assessment on demand | Servicer |
| GET | `/lessors/{lessorId}/tax-assessments/{id}` | Get a tax assessment | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/tax-assessments` | List tax assessments for a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/tax-assessments/{id}/remit` | Mark a tax assessment remitted | Servicer |
| POST | `/lessors/{lessorId}/leases/{id}/add-ons` | Propose a mid-term add-on or upgrade | Servicer |
| GET | `/lessors/{lessorId}/add-ons/{id}` | Get an add-on | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/add-ons` | List add-ons for a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/equipment/{id}/add-ons` | List add-ons that replace this EquipmentUnit | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/leases/{id}/add-ons/{id}/apply` | Apply an add-on | Servicer |
| POST | `/lessors/{lessorId}/leases/{id}/add-ons/{id}/reject` | Reject a proposed add-on | Servicer |
| POST | `/lessors/{lessorId}/leases/{id}/eot-elections` | Record an end-of-term election | Servicer |
| GET | `/lessors/{lessorId}/eot-elections/{id}` | Get an end-of-term election | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| GET | `/lessors/{lessorId}/leases/{id}/eot-elections` | List end-of-term elections for a lease | CreditAnalyst, FundingOfficer, Servicer, AssetManager |
| POST | `/lessors/{lessorId}/leases/{id}/eot-elections/{id}/exercise` | Exercise an elected end-of-term option | Servicer |
| POST | `/lessors/{lessorId}/leases/{id}/eot-elections/{id}/cancel` | Cancel an elected end-of-term option | Servicer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_APPROVED_EXCEEDS_REQUESTED` | 409 Conflict |
| `ERR_SCORE_BELOW_FLOOR` | 409 Conflict |
| `ERR_TRAC_RESIDUAL_REQUIRED` | 409 Conflict |
| `ERR_NO_EQUIPMENT` | 409 Conflict |
| `ERR_VENDOR_NOT_APPROVED` | 409 Conflict |
| `ERR_NOT_BOOKED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_TERM_NOT_COMPLETE` | 409 Conflict |
| `ERR_LEASE_NOT_END_OF_TERM` | 409 Conflict |
| `ERR_BUYOUT_NOT_PAID` | 409 Conflict |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_OUTSTANDING_BALANCE` | 409 Conflict |
| `ERR_ELECTION_NOT_EXERCISED` | 409 Conflict |
| `ERR_ELECTION_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_LEASE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_DUE` | 409 Conflict |
| `ERR_SERIAL_REUSE_TOO_SOON` | 409 Conflict |
| `ERR_UCC_OVERLAP` | 409 Conflict |
| `ERR_UCC_WRONG_JURISDICTION` | 409 Conflict |
