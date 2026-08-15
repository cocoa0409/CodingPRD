# Building Materials Reuse API — Product Requirements Document

## 1. Introduction

A building-materials reuse warehouse lives or dies by flow: donated cabinets, salvaged doors, reclaimed lumber, and deconstruction leftovers arrive through the back dock, and every pound that leaves as a retail sale, a donation, or a recycling stream is a pound diverted from landfill. The operation behind that flow is surprisingly demanding. Intake staff must decide what is acceptable and what is not, certified technicians must screen salvage for lead and asbestos before a single board is pulled, volunteer and paid crews must be scheduled against trucks that cannot be in two places at once, the sales floor must turn slow stock over through disciplined markdowns, contractors expect account terms and volume pricing, donors expect defensible tax receipts, and the organization must be able to certify its diversion tonnage at the end of every reporting month.

This document specifies the API that runs such a warehouse end to end. It governs the donor registry and the donation offer pipeline, hazardous-material screening and the remediation loop, crew and fleet scheduling, salvage weighing and quarantine, item pricing and floor merchandising, the register, contractor trade accounts with credit enforcement, tax receipt issuance and correction, and period diversion reporting. All endpoints are mounted under the `/reuse` prefix. The specification is written so that segregation of duties — the receiver of goods may not issue their tax receipt, and the technician who cleared a job may not lead it — is enforced by the API itself rather than by policy memos.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Nine roles are recognized, spelled exactly as follows: `Donor`, `IntakeStaff`, `HazmatTechnician`, `CrewCoordinator`, `CrewLead`, `StoreManager`, `Cashier`, `Contractor`, and `WarehouseAdmin`.

For some roles the `X-User-ID` header is bound to a persisted entity; for others it is an opaque operator identifier. The bindings are:

- When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor`; ownership checks on any resource that references a `Donor` — donation offers and tax receipts — compare the resource's `donor_id` foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). On the offer and tax-receipt list endpoints, a `Donor` caller who explicitly passes a `donor_id` filter other than their own `id` is likewise rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `ContractorAccount`; ownership checks on contractor accounts, sales, and bulk purchase agreements compare the resource's `contractor_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. On the sales and bulk-agreement list endpoints, a `Contractor` caller who explicitly passes a `contractor_id` filter other than their own `id` is likewise rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `HazmatTechnician`, `X-User-ID` is the `id` of the acting `CrewMember`; a screening is recorded with `performed_by_crew_id` taken from `X-User-ID`, so a technician can only record screenings as themselves.
- When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `CrewMember`; the lead-ownership binding is enforced where a `CrewLead` acts on a specific job's lifecycle — starting or completing it (§3.4): the job's `lead_crew_member_id` must equal `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. Other operations open to the `CrewLead` role — manifesting or weighing salvage batches, reading jobs and batches — carry no per-job ownership check.
- When `X-User-Role` is `IntakeStaff`, `CrewCoordinator`, `StoreManager`, `Cashier`, or `WarehouseAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `received_by_user_id` on a `DonationOffer`, `priced_by_user_id` on an `Item`, `approved_by_user_id` on a `ContractorAccount`, `issued_by_user_id` on a `TaxReceipt`, or `closed_by_user_id` on a `DiversionReport` — but does not compare it to any entity's `id`.

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

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of resources returned: it defaults to 10 when omitted, and clients may ask for no fewer than 1 and no more than 100 per page. The `offset` parameter says how many resources to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Derived State

The warehouse runs on a server-held logical clock, not on wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `WarehouseAdmin` may advance it through a test-driving capability that accepts a `to_iso8601` instant and answers with the new `current_utc`; everything time-derived in this document reads that clock. Concretely, an item's `days_on_floor`, the trailing 365-day windows behind donor recognition tiers and contractor discount tiers, the `report_period` stamped when a batch is weighed, the calendar year inside a receipt's `receipt_number`, and the lazy expiry of bulk purchase agreements are all evaluated against the logical clock. Agreement expiry in particular is lazy: an `ACTIVE` agreement whose `valid_until` the clock has passed flips to `EXPIRED` the next time the agreement is read or used, not through any background sweep.

### 2.5. Common Resource Properties and the Audit Trail

Every top-level resource carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 at creation and increments by one on every mutation, including mutations the server performs as cascade side effects.

Three resources are deliberately leaner: a `HazmatScreening`, a `MarkdownRun`, and a `SaleLineItem` each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these three; they are never mutated after creation, so there is nothing to version.

### 2.6. Money, Weight, and Rounding Conventions

All monetary values — prices, fees, balances, valuations, labor costs — are represented as integer cents. Wherever a calculation produces a fractional cent, the result is rounded half-up to integer cents at exactly the step the rule specifies; rounding earlier or later is non-conformant. Percentages and multipliers (discount fractions, markdown step fractions, condition factors, the tax rate) are exact fractional numbers.

Weights are tracked in pounds at a precision of one decimal place. Tonnage rollups on deconstruction jobs and diversion reports carry that same one-decimal-pound precision.

Counts — a zone's `current_count`, an item's `markdown_step`, a screening's `screening_round` — are plain integers.

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the API take an optimistic-concurrency version field, and for both it is a required, non-optional input. No other endpoint accepts or requires a version field.

- Creating a bulk purchase agreement — `POST /reuse/bulk-agreements` — requires `expected_account_version`, carrying the `version` of the parent contractor account as the client last observed it. If the account's current `version` has moved past that value — because another writer has since mutated the account, for example by creating an agreement that superseded the previously active one — the create is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), preventing the client from writing against a stale view of the account.
- Amending a tax receipt — `POST /reuse/tax-receipts/{receiptId}/amend` — requires `expected_receipt_version`, matching the target receipt's current `version`. A successful amendment supersedes the receipt and bumps its version, so a client carrying a pre-amendment version holds a stale view; its amendment is rejected with `ERR_STALE_RECEIPT_VERSION` (HTTP 412).

### 2.8. Identifier Validation and Referential Integrity

Requests are validated left to right. When a path carries resource identifiers, the system confirms each identifier exists before evaluating anything further along, and the first missing identifier produces that resource's own not-found error: `ERR_DONOR_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_CREW_MEMBER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, each an HTTP 404.

Foreign keys carried in request bodies are checked the same way: a payload naming a `donor_id`, `category_id`, `allowed_category_id`, `item_id`, `zone_id`, `contractor_id`, `agreement_id`, `job_id`, `deconstruction_job_id`, `crew_member_id`, `vehicle_id`, `subject_id` (interpreted per its `subject_type`), `screening_id`, `offer_id`, `batch_id`, or `supersedes_agreement_id` that does not resolve to an existing resource is rejected with the corresponding not-found error from the list above (`allowed_category_id` resolves as a category, `deconstruction_job_id` as a job).

### 2.9. Diversion Accounting as a Ledger

Diversion tonnage behaves like a ledger, not a snapshot. While a period's `DiversionReport` stands `OPEN`, its running totals recompute on every relevant event — a batch weigh, a quarantine, a quarantine resolution, a walk-in sale finalizing, an item disposition — so the report always reflects period activity to date. Mutations that disqualify previously counted tonnage compensate rather than rewrite history: quarantining a weighed batch subtracts its diverted pounds from the job's certified total and from the open report, and voiding a sale reverses its account and agreement effects. Batch-derived material and walk-in material are accounted in separate streams so that goods arriving through a salvage batch are never double counted once they later become items. Two tonnage figures are kept side by side — an estimated figure and a certified figure — and they are expected to diverge whenever crew estimates differ from scale weights or contamination is present. Closing a report is an ops-run checkpoint: the figures freeze at close, and a `CLOSED` report never recomputes, no matter what later happens in that period.

### 2.10. The Validation Cascade: Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order, and the first failing check produces the response. Malformed requests — a missing required field, a type mismatch, an unknown enum member, or a non-positive quantity where a positive one is required — fail with `ERR_INVALID_REQUEST` (HTTP 400). Beyond request shape, the cascade runs in this order:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the nine declared roles, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the acting role is listed in the endpoint's authorized roles, else `ERR_FORBIDDEN_ROLE`.
3. **Entity-backed ownership** — donor, contractor, technician, and crew-lead ownership bindings from §2.1 hold, else `ERR_NOT_RESOURCE_OWNER`.
4. **Path existence** — path identifiers resolve, validated left to right, else the matching `ERR_{RESOURCE}_NOT_FOUND`.
5. **Body reference existence** — foreign keys in the payload resolve, else the matching `ERR_{RESOURCE}_NOT_FOUND`.
6. **Optimistic concurrency** — on the two OCC-guarded writes, the expected version matches, else `ERR_STALE_ACCOUNT_VERSION` or `ERR_STALE_RECEIPT_VERSION`.
7. **State** — the target resource stands in the from-state the transition requires, else the per-entity state error (§5), each an HTTP 409.
8. **Hazardous-material and segregation-of-duties safety** — screening inheritance on hazmat-exposed item intake, open quarantines blocking job completion, screener-versus-lead separation, and receipt issuer-versus-receiver separation, producing `ERR_HAZMAT_SCREENING_REQUIRED`, `ERR_QUARANTINED_BATCHES_OPEN`, `ERR_SCREENER_CANNOT_LEAD`, or `ERR_RECEIPT_ISSUER_IS_RECEIVER`.
9. **Business constraints** — uniqueness of codes, plates, and report periods; crew and vehicle time overlaps; zone capacity and category fit; certifications; acceptance grading; category acceptance status; crew presence at job start; weigh-time weight bounds; active-appointment and weighed-batch blocks: `ERR_DUPLICATE_CODE`, `ERR_DUPLICATE_REPORT_PERIOD`, `ERR_CREW_TIME_OVERLAP`, `ERR_VEHICLE_TIME_OVERLAP`, `ERR_ZONE_AT_CAPACITY`, `ERR_ZONE_CATEGORY_MISMATCH`, `ERR_CAPACITY_BELOW_OCCUPANCY`, `ERR_CERTIFICATION_MISMATCH`, `ERR_CONDITION_BELOW_ACCEPTANCE`, `ERR_CATEGORY_NOT_ACCEPTING`, `ERR_NO_CREW_ASSIGNED`, `ERR_INVALID_WEIGHTS`, `ERR_ACTIVE_APPOINTMENT_EXISTS`, `ERR_JOB_HAS_WEIGHED_BATCHES`.
10. **Temporal arithmetic** — window end strictly after window start, assignment containment inside the job window, agreement validity windows, split quantity bounds: `ERR_INVALID_TIME_WINDOW`, `ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW`, `ERR_AGREEMENT_NOT_IN_WINDOW`, `ERR_SPLIT_INVALID_QUANTITY`.
11. **Fiscal checks** — credit-limit breaches, payment sufficiency, overpayment, zero-balance on close, appraisal thresholds: `ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_PAYMENT_INSUFFICIENT`, `ERR_OVERPAYMENT`, `ERR_OUTSTANDING_BALANCE_NONZERO`, `ERR_APPRAISAL_REQUIRED`.
12. **Referential linkage** — one non-terminal receipt per offer, received-state requirements for receipt drafting and offer-linked item intake, category consistency between linked resources, deconstruction offer linkage, supersede references: `ERR_ACTIVE_RECEIPT_EXISTS`, `ERR_INVALID_OFFER_STATE`, `ERR_CATEGORY_MISMATCH`, `ERR_JOB_CANCELLED`, `ERR_AGREEMENT_NOT_ACTIVE`.

## 3. Business Logic & Workflows

### 3.1. The Donor Registry and Recognition Standing

Everything a donor ever gives accumulates into a single `Donor` record, opened by an `IntakeStaff` operator or a `WarehouseAdmin` with a `full_name` (an individual or an organization), a `donor_type` of `INDIVIDUAL`, `BUSINESS`, or `CONTRACTOR`, a contact `email`, an optional `phone` that defaults to an empty string, and the `address_text` to which tax receipts are mailed. A donor is `ACTIVE` on creation and can later be deactivated to `INACTIVE` by intake staff or an administrator — but only while the donor has no donation offer standing in `OFFERED`, `UNDER_REVIEW`, `NEEDS_INFO`, or `ACCEPTED`; an open pipeline blocks deactivation with `ERR_INVALID_OFFER_STATE`. Reactivation from `INACTIVE` back to `ACTIVE` is unconditional. Staff can list and filter donors by `status` or `recognition_tier`; a caller in the `Donor` role may read only their own record.

Recognition is earned, not declared. Each donor carries a `trailing_receipt_value_cents`, the sum of `valued_total_cents` over the donor's tax receipts standing in `ISSUED` or `SUPERSEDED` status — `VOIDED` receipts are excluded, as are receipts still in `DRAFT` or `VOID_REQUESTED` — whose `issued_at` falls inside the inclusive window from 365 days before the logical clock up to the clock itself, both bounds included. Within a supersede chain only the newest receipt contributes, since the superseding receipt carries the chain's value and counting both would double count. From that trailing figure the system derives the donor's `recognition_tier`: at least $10,000 (1,000,000 cents) earns `CORNERSTONE`, at least $2,500 (250,000 cents) earns `BUILDER`, at least $500 (50,000 cents) earns `SUPPORTER`, and anything less is `NONE`; every threshold is inclusive. A freshly registered donor starts at 0 cents and tier `NONE`. The trailing value and tier are recomputed on every event that changes the donor's issued-receipt set — a receipt being issued, a void being confirmed, an amendment replacing a receipt.

### 3.2. The Donation Offer Pipeline

Materials arrive at the warehouse as offers. A donation offer is created by the donor themselves or by an `IntakeStaff` operator on their behalf; a caller in the `Donor` role must name their own `id` as the `donor_id`, otherwise the create is refused with `ERR_NOT_RESOURCE_OWNER`. The payload names the primary `category_id` of the offered materials, a free-text `description_text`, an `estimated_quantity` that must be greater than zero expressed in a `quantity_unit` of `UNIT`, `SQFT`, or `LINEAR_FT`, a `condition_grade` of `A` (like-new) through `D` (salvage-only), and a `pre_1978_flag` marking material installed or painted before 1978 and therefore suspect for lead paint. The `source_type` declares how the materials will arrive: `DROPOFF` at the dock, `PICKUP` by a warehouse truck, or `DECONSTRUCTION` from a salvage job. Both valuation fields on the offer, `estimated_value_cents` and `final_value_cents`, start at 0 and stay there until acceptance computes the first and receipt issuance the second. A deconstruction-sourced offer must name its `deconstruction_job_id`; any other source leaves it null, and a deconstruction offer missing the job reference fails with `ERR_JOB_CANCELLED`. New offers stand in `OFFERED`.

Offers are judged against the warehouse's category policies. Each `Category` — created by a `StoreManager` or `WarehouseAdmin` with a `code` unique across all categories (a clash is `ERR_DUPLICATE_CODE`), a `display_name`, and a pricing and markdown policy — declares whether it is taking material at all through its `acceptance_status`. Categories are born `ACCEPTING`, can be paused to `PAUSED` and resumed, and can be retired from either `ACCEPTING` or `PAUSED` to terminal `RETIRED` — any `acceptance_status` change outside those four edges is rejected with `ERR_INVALID_REQUEST`; retirement leaves existing items to finish their lifecycle but new offers and items naming the category are refused. Categories list with a filter on `acceptance_status`. The policy fields a category carries are its `pricing_model` (`PER_UNIT`, `PER_SQFT`, `PER_LINEAR_FT`, or `FLAT`), the `base_rate_cents` list rate per unit of that model, a `hazmat_risk_flag` for categories carrying lead or asbestos risk such as pre-1978 paint, insulation, or floor tiles, a `requires_appraisal_review` flag (default false) for architectural salvage and antiques that always get appraisal guidance, the markdown policy fields `markdown_after_days`, `markdown_step_pct`, `markdown_interval_days`, `max_markdown_steps`, and `floor_price_pct` detailed in §3.8, a `divertible` flag (default true) saying whether its material counts toward diversion tonnage, a `target_turn_days` merchandising target, and a `slow_item_disposition` of `DONATE`, `RECYCLE`, or `DISPOSE` (default `DONATE`) recommending what to do with stock that exhausts its markdowns.

Review begins when an intake operator moves an `OFFERED` offer to `UNDER_REVIEW`; from any other state the request fails with `ERR_INVALID_OFFER_STATE`. If the paperwork is thin, the operator requests more information, pushing the offer to `NEEDS_INFO` with `review_notes` recording what is missing. The donor — or staff on their behalf, with donor callers again bound to their own `donor_id` — resubmits from `NEEDS_INFO` back to `UNDER_REVIEW`, optionally revising `description_text`, `estimated_quantity`, or `condition_grade`; this review-and-revision loop is unbounded.

Acceptance is the pivotal decision and enforces its checks strictly. The offer must stand in `UNDER_REVIEW` (`ERR_INVALID_OFFER_STATE`), its category must be `ACCEPTING` (`ERR_CATEGORY_NOT_ACCEPTING`), and its `condition_grade` must be `A`, `B`, or `C` — grade `D` material is below acceptance criteria and fails with `ERR_CONDITION_BELOW_ACCEPTANCE`. A deconstruction-sourced offer additionally requires that its linked job has not been `CANCELLED` (`ERR_JOB_CANCELLED`). On acceptance the system computes the donor's provisional guidance figure, `estimated_value_cents`: the category's `base_rate_cents` — verbatim for a `FLAT` category, otherwise multiplied by the offer's `estimated_quantity` — is multiplied by a condition factor of 1.00 for grade `A`, 0.75 for `B`, 0.50 for `C`, or 0.25 for `D`, then by a thirty percent thrift-value rate, and the product is rounded half-up to integer cents. An offer may instead be rejected from `UNDER_REVIEW`, recording the staff `decision_reason` and landing in terminal `REJECTED`.

Offers can be withdrawn. Cancelling from `OFFERED`, `UNDER_REVIEW`, or `NEEDS_INFO` needs no further condition beyond the ownership binding when a `Donor` acts; cancelling from `ACCEPTED` additionally requires that no `BOOKED` pickup appointment still references the offer, else `ERR_ACTIVE_APPOINTMENT_EXISTS`. All four edges land in terminal `CANCELLED`. The offer ledger can be listed filtered by `donor_id`, `status`, `category_id`, or `deconstruction_job_id`, with donors seeing only their own offers.

### 3.3. Receiving, Tax Receipts, and the Correction Cycle

An `ACCEPTED` offer becomes inventory only at receiving, performed by an `IntakeStaff` operator. Receiving demands the offer stand in `ACCEPTED` (`ERR_OFFER_NOT_ACCEPTED`) and then enforces provenance: a `PICKUP` offer is receivable only once a pickup appointment naming the offer as its `DONATION_OFFER` subject has reached `COMPLETED`; a `DECONSTRUCTION` offer only once its linked deconstruction job stands `COMPLETED`; a `DROPOFF` offer carries no such gate. Breaching the provenance gate fails with `ERR_OFFER_NOT_RECEIVABLE_SOURCE`. Receiving lands the offer in `RECEIVED` and records the acting operator's `X-User-ID` in the offer's `received_by_user_id` — the segregation-of-duties anchor consumed when the receipt is later issued.

With goods physically in the building, an intake operator drafts a `TaxReceipt` for the offer. Drafting requires the offer to stand in `RECEIVED` (`ERR_INVALID_OFFER_STATE`), and an offer may carry at most one non-terminal receipt — one standing in `DRAFT`, `ISSUED`, or `VOID_REQUESTED`; drafting a second while one stands is refused with `ERR_ACTIVE_RECEIPT_EXISTS`. The draft copies `donor_id` and `received_by_user_id` from the offer, leaves `valuation_method` null and `valued_total_cents` at 0 until issue pins them, and is numbered automatically: `receipt_number` follows the pattern R-<yyyy>-<seq>, where the year is the calendar year of the logical clock and the sequence is the 1-based count of receipts created in that calendar year, assigned in `created_at` order.

Issuance is a second, deliberate act by an `IntakeStaff` operator, and the warehouse keeps the two hands apart: the operator issuing the receipt must not be the one who received the goods, so an `X-User-ID` equal to the receipt's `received_by_user_id` is refused with `ERR_RECEIPT_ISSUER_IS_RECEIVER`. The receipt must stand in `DRAFT` (`ERR_RECEIPT_NOT_DRAFT`) and its offer must still stand in `RECEIVED` (`ERR_INVALID_OFFER_STATE`). At issue, the receipt's value is pinned by a two-path rule. Let the item sum be the total of `list_price_cents` over all items linked to the receipt's offer that are `PRICED` and stand in `BACKROOM`, `ON_FLOOR`, `RESERVED`, or `SOLD`; goods that already left the stream as `DONATED_OUT`, `RECYCLED`, or `DISPOSED` cannot be valued. When that item sum is at least $5,000 (500,000 cents) — the threshold is inclusive, so a sum of exactly $5,000 crosses it — or when the offer's category carries `requires_appraisal_review`, the receipt takes the `QUALIFIED_APPRAISAL` path: both `appraisal_reference` and `appraisal_value_cents` are mandatory (missing either fails with `ERR_APPRAISAL_REQUIRED`), and `valued_total_cents` becomes the appraised value verbatim, even though the identical items would sum to a different number. Below the threshold with no appraisal-review category, the receipt takes the `ESTIMATED_GUIDANCE` path and `valued_total_cents` is the item sum. The chosen path is recorded in `valuation_method`, and issuance stamps `issued_by_user_id` and `issued_at` from the acting operator and the logical clock. Issuing ripples outward: the offer moves from `RECEIVED` to `RECEIPTED` and its `final_value_cents` is set to the issued `valued_total_cents`, the donor's trailing receipt value and recognition tier are recomputed, and the receipt, offer, and donor each bump their `version`.

Corrections follow a supervised cycle. The issuing side can ask for a void, moving an `ISSUED` receipt to `VOID_REQUESTED` with a recorded `void_reason`; from any other state the request fails with `ERR_RECEIPT_NOT_ISSUED`. A `WarehouseAdmin` then adjudicates. Confirming the void requires `VOID_REQUESTED` (`ERR_RECEIPT_NOT_VOID_REQUESTED`) and lands the receipt in terminal `VOIDED`, reverts the offer from `RECEIPTED` back to `RECEIVED` with `final_value_cents` reset to 0 so a corrected receipt may be drafted, and recomputes the donor's trailing value and tier. Rejecting the void — the same state gate, the same `ERR_RECEIPT_NOT_VOID_REQUESTED` — returns the receipt to `ISSUED` and clears the `void_reason`, restoring the pre-request state exactly.

When the valuation itself was wrong, an `IntakeStaff` operator amends instead. Amendment requires the receipt to stand in `ISSUED` (`ERR_RECEIPT_NOT_ISSUED`), carries the mandatory `expected_receipt_version` OCC check from §2.7, upholds the same issuer-versus-receiver separation (`ERR_RECEIPT_ISSUER_IS_RECEIVER`), and enforces the same appraisal mandate — at or above the $5,000 threshold, or for an appraisal-review category, fresh `appraisal_reference` and `appraisal_value_cents` are required, else `ERR_APPRAISAL_REQUIRED`. A successful amendment turns the amended receipt `SUPERSEDED` and bumps its `version`, creates the replacement receipt directly in `ISSUED` with `supersedes_receipt_id` pointing at the receipt it replaces, values the replacement per the same two-path rule, and recomputes the donor's trailing value and recognition tier over the replacement chain. Receipts can be listed filtered by `donor_id`, `offer_id`, `status`, or `supersedes_receipt_id`; a caller in the `Donor` role sees only receipts naming their own `donor_id`.

### 3.4. Deconstruction Jobs: Screening, Scheduling, and Remediation

A deconstruction job is the warehouse's most regulated workflow: a crew enters a building, salvages material, and nothing moves until hazardous-material screening says it may. A `CrewCoordinator` or `WarehouseAdmin` opens a job with a `title`, the `site_address_text`, an optional `donor_id` for the site owner donating the salvage, a fixed `quoted_fee_cents` for the service, and an `included_labor_cents` amount of paid-crew labor folded into the quote before overage billing (default 0). The job starts in `REQUESTED`, its two tonnage ledgers `estimated_diverted_weight_lbs` and `certified_diverted_weight_lbs` start at 0, and `actual_fee_cents` starts at 0 until crew completions recompute it (§3.5). Jobs can be listed filtered by `status`, `donor_id`, `lead_crew_member_id`, `vehicle_id`, or `clearing_screening_id`.

Screening comes first. The coordinator requests screening, moving the job from `REQUESTED` to `SCREENING_PENDING`; from any other state the request fails with `ERR_INVALID_JOB_STATE`. A `HazmatTechnician` — who must hold hazmat certification, else `ERR_CERTIFICATION_MISMATCH` — records a `HazmatScreening` naming the `job_id`, a `lead_result` and an `asbestos_result`, each one of `NOT_TESTED`, `NEGATIVE`, or `POSITIVE`, and optional technician `notes`. The screening's `performed_by_crew_id` is taken from the technician's own `X-User-ID`, its `screening_round` is the 1-based count of screenings recorded for that job in `created_at` order, and its `outcome` is computed: `CLEARED` when both results are `NEGATIVE`, `FAILED` when either result is `POSITIVE`, and `PENDING` otherwise. Screenings list with filters on `job_id`, `performed_by_crew_id`, or `outcome`.

The outcome moves the job without any further request. A `CLEARED` outcome on a `SCREENING_PENDING` job moves it to `CLEARED` and records the screening's `id` as the job's `clearing_screening_id`; a `FAILED` outcome on a `SCREENING_PENDING` job moves it to `HAZMAT_HOLD`. A `FAILED` outcome can also arrive post-hoc, while the job is already `IN_PROGRESS`: the job drops to `HAZMAT_HOLD`, every one of its batches standing in `WEIGHED` is forced to `QUARANTINED`, and each quarantined batch's diverted pounds are subtracted from the job's certified tonnage — a conditional cascade with compensation. A `PENDING` outcome moves nothing.

From `HAZMAT_HOLD` the coordinator begins remediation, moving the job to `REMEDIATION_IN_PROGRESS` (any other from-state fails with `ERR_JOB_NOT_IN_HAZMAT_HOLD`), and when the cleanup is done, completing remediation returns the job to `SCREENING_PENDING` (from any other state, `ERR_JOB_NOT_REMEDIATING`) for a fresh screening round. The screening–hold–remediation loop is unbounded, and each pass through it increments the job's screening count.

Only a `CLEARED` job can be scheduled (`ERR_JOB_NOT_CLEARED` otherwise). Scheduling assigns the `lead_crew_member_id`, the `vehicle_id`, and the job window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive), and enforces a battery of checks. Segregation of duties bars the technician who cleared the job from leading it: a proposed lead equal to the clearing screening's `performed_by_crew_id` is refused with `ERR_SCREENER_CANNOT_LEAD`. The named lead must be an `ACTIVE` crew member holding lead certification (`ERR_CERTIFICATION_MISMATCH`). The vehicle must stand `AVAILABLE` (`ERR_VEHICLE_NOT_AVAILABLE`), the window's end must be strictly after its start (`ERR_INVALID_TIME_WINDOW`), and the vehicle must be free of conflicting occupations under the buffered overlap rule of §3.5 — no other `SCHEDULED` or `IN_PROGRESS` job on that vehicle whose window comes within 60 minutes of the new one, and no `BOOKED` pickup appointment on that vehicle failing the same buffer (`ERR_VEHICLE_TIME_OVERLAP`). A scheduled job then moves from `SCHEDULED` to `IN_PROGRESS` when started; the coordinator or the job's own lead may start it — a `CrewLead` caller whose `X-User-ID` is not the job's `lead_crew_member_id` is refused with `ERR_NOT_RESOURCE_OWNER` — the job must stand in `SCHEDULED` (`ERR_JOB_NOT_SCHEDULED`), and at least one crew assignment must stand `ASSIGNED` for the job (`ERR_NO_CREW_ASSIGNED`). Completion, by the coordinator or the assigned lead under the same ownership rule, requires the job to be `IN_PROGRESS` (`ERR_JOB_NOT_IN_PROGRESS`) and no batch of the job to stand `QUARANTINED` (`ERR_QUARANTINED_BATCHES_OPEN`); completion lands the job in terminal `COMPLETED` with its certified tonnage finalized from its `WEIGHED` and `SORTED` batches.

Cancellation is always available to the coordinator or a `WarehouseAdmin`, with consequences that grow as the job matures. From `REQUESTED`, `SCREENING_PENDING`, `CLEARED`, `HAZMAT_HOLD`, or `REMEDIATION_IN_PROGRESS` the job simply lands in terminal `CANCELLED`. From `SCHEDULED`, the cancellation cascades downward: every crew assignment of the job still `ASSIGNED` is cancelled, and every pickup appointment booked for the job as a `DECONSTRUCTION_JOB` subject and still `BOOKED` is cancelled. From `IN_PROGRESS` the same two cascades run, the job may not be cancelled while any of its batches stands `WEIGHED` or `SORTED` (`ERR_JOB_HAS_WEIGHED_BATCHES`), and any batch still `MANIFESTED` is pushed to `DISPOSED_HAZARD` with its full `estimated_weight_lbs` booked as `contamination_weight_lbs` — nothing from it is diverted. Cancelling a job already in a terminal state (`COMPLETED` or `CANCELLED`) fails with `ERR_INVALID_JOB_STATE`. Once a job reaches a terminal state, both tonnage ledgers freeze at their last values.

### 3.5. Crew, Fleet, and Pickup Logistics

Deconstruction labor mixes volunteers and paid crew. A `CrewCoordinator` or `WarehouseAdmin` registers each `CrewMember` with a `full_name`, a `crew_type` of `VOLUNTEER` or `PAID`, an `hourly_rate_cents` (forced to 0 for volunteers whatever the payload says, both at registration and on any later update), and two certifications that default to false: `hazmat_certified`, required to record screenings, and `lead_certified`, required to lead a job. Members are `ACTIVE` on registration, can be patched between `ACTIVE` and `INACTIVE` or have their rate and certifications updated, and accumulate `cumulative_job_hours` — the sum of `hours_worked` over their `COMPLETED` assignments — starting from 0. The roster lists with filters on `status`, `crew_type`, or `hazmat_certified`.

Staffing a job means creating `CrewAssignment` records naming the `job_id`, the `crew_member_id`, a `role_on_job` of `LEAD` or `WORKER`, and an assignment window from `start_at` (inclusive) to `end_at` (exclusive) whose end must be strictly after its start (`ERR_INVALID_TIME_WINDOW`). The window must lie inside the job's scheduled window — an assignment that begins before the job's `scheduled_start` or ends after its `scheduled_end` fails with `ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW`. Assignments for the same crew member follow half-open interval semantics: a new assignment conflicts with an existing `ASSIGNED` or `COMPLETED` assignment of that member only when the existing window starts before the new window ends and ends after the new window starts, and any such conflict is rejected with `ERR_CREW_TIME_OVERLAP`. Adjacent windows — one ending exactly when the next begins — are legal and carry no buffer, and assignments in `NO_SHOW` or `CANCELLED` never conflict. Assignments list with filters on `job_id`, `crew_member_id`, or `status`.

Every assignment starts `ASSIGNED`. When the work is done the coordinator completes it with a positive `hours_worked` (a non-positive value fails with `ERR_INVALID_REQUEST`), which lands the assignment in `COMPLETED` and triggers the labor ledger: the assignment's `labor_cost_cents` is 0 for a `VOLUNTEER` and the half-up-rounded product of `hours_worked` and the member's `hourly_rate_cents` for `PAID` crew; the member's `cumulative_job_hours` grows by the hours worked; and the job's `actual_fee_cents` is recomputed as the `quoted_fee_cents` plus the amount — never below zero — by which the summed `labor_cost_cents` of the job's completed paid assignments exceeds the quote's `included_labor_cents`. That recomputation runs on every assignment completion and every assignment cancellation. An assignment can instead be marked `NO_SHOW` or cancelled outright; completing, cancelling, or marking no-show from any state other than `ASSIGNED` fails with `ERR_ASSIGNMENT_NOT_ACTIVE`, and a job cancellation cancels its still-`ASSIGNED` assignments as a cascade.

The fleet is small and every booking competes for it. A vehicle is registered by a `plate_code` unique across all vehicles (`ERR_DUPLICATE_CODE`) and a `capacity_lbs` payload that must be greater than zero, and starts `AVAILABLE`. A coordinator or administrator can send a vehicle to `IN_MAINTENANCE` — only while no `BOOKED` pickup appointment references it, else `ERR_ACTIVE_APPOINTMENT_EXISTS` — return it to `AVAILABLE`, or retire it from `IN_MAINTENANCE` to terminal `RETIRED`; any other status transition is rejected with `ERR_INVALID_REQUEST`. Vehicles list with a filter on `status`.

Pickup appointments bind the fleet to both halves of the business. Booking one, by a `CrewCoordinator` or `IntakeStaff`, names a polymorphic subject — `subject_type` of `DONATION_OFFER` or `DECONSTRUCTION_JOB` with the matching `subject_id` — a `vehicle_id`, and a pickup window from `window_start` (inclusive) to `window_end` (exclusive) whose end must be strictly after its start (`ERR_INVALID_TIME_WINDOW`). The subject must be in a bookable state: a `DONATION_OFFER` subject must stand `ACCEPTED` (`ERR_INVALID_OFFER_STATE`), a `DECONSTRUCTION_JOB` subject must stand `SCHEDULED` or `IN_PROGRESS` (`ERR_INVALID_JOB_STATE`), and the vehicle must be `AVAILABLE` (`ERR_VEHICLE_NOT_AVAILABLE`). Vehicle scheduling uses buffered overlap semantics, stricter than the crew rule: a vehicle is occupied by its `BOOKED` appointments and its `SCHEDULED` or `IN_PROGRESS` jobs, and a new window does not conflict with an existing occupation only when the new window's end, extended by a 60-minute buffer, is still at or before the existing window's start, or the new window's start is at or after the existing window's end extended by the same buffer. Touching windows without that full one-hour gap are rejected with `ERR_VEHICLE_TIME_OVERLAP` — where the crew rule lets adjacent windows pass, the vehicle rule does not.

The booking computes its `fee_cents` once, at booking time. A `DECONSTRUCTION_JOB` subject always rides free. For a `DONATION_OFFER` subject the fee reads the donor's recognition standing at that moment: donors at `BUILDER` or `CORNERSTONE` pay nothing, while `NONE` and `SUPPORTER` donors are charged a flat $50 (5,000 cents). Appointments live as `BOOKED` until the coordinator or intake staff completes them, marks them `NO_SHOW`, or cancels them — each requiring the `BOOKED` state (`ERR_APPOINTMENT_NOT_BOOKED`) — with `completion_notes` recorded on completion or no-show. A job cancellation cascades to its still-`BOOKED` appointments, and cancelling an `ACCEPTED` offer is blocked while one of its appointments stands `BOOKED` (§3.2). Appointments list with filters on `vehicle_id`, `subject_id`, or `status`.

### 3.6. Salvage Batches and Certified Tonnage

Everything a crew pulls from a site is manifested as a `SalvageBatch`. A `CrewLead` or the `CrewCoordinator` manifests a batch under a job that must stand `SCHEDULED` or `IN_PROGRESS` (any other job state fails with `ERR_INVALID_JOB_STATE`), naming the `job_id`, the dominant `category_id`, the crew's `estimated_weight_lbs` (which must be greater than zero), and optionally the `offer_id` of the deconstruction-sourced donation offer expecting these materials. The batch starts `MANIFESTED` with `scale_weight_lbs`, `contamination_weight_lbs`, and `diverted_weight_lbs` all at 0 and no `weighed_at` — the diverted figure stays 0 until the first weigh — and the job's estimated tonnage immediately gains the estimate. Batches list with filters on `job_id`, `offer_id`, `category_id`, `status`, or `report_period`.

Weighing is the moment estimates become certified. A crew lead or the coordinator weighs a `MANIFESTED` batch — any other batch state fails with `ERR_BATCH_NOT_WEIGHABLE` — while its job stands `IN_PROGRESS` or `COMPLETED` (`ERR_JOB_NOT_IN_PROGRESS`). The weigh takes the certified `scale_weight_lbs`, which must be greater than zero, and an optional `contamination_weight_lbs` for non-divertible contamination, which defaults to 0 and must be at least zero and no more than the scale weight; weights violating those bounds are rejected with `ERR_INVALID_WEIGHTS`. The weigh cascade then runs three hops. First, the batch lands in `WEIGHED`, its `diverted_weight_lbs` is computed as the scale weight minus the contamination weight, `weighed_at` is stamped from the logical clock, and `report_period` is derived as the year-and-month (`YYYY-MM`) of that timestamp, staying empty until the batch is weighed. Second, the job's certified diverted tonnage rises by the batch's diverted pounds. Third, the `OPEN` diversion report for that period recomputes its running totals.

The two tonnage ledgers on the job now diverge by design. The estimated figure, `estimated_diverted_weight_lbs`, sums `estimated_weight_lbs` over the job's batches in `MANIFESTED`, `WEIGHED`, `QUARANTINED`, or `SORTED` — every batch except those `DISPOSED_HAZARD`. The certified figure, `certified_diverted_weight_lbs`, sums `diverted_weight_lbs` over the job's batches in `WEIGHED` or `SORTED` whose category counts toward diversion (`divertible`); the same job and the same batches therefore yield different numbers whenever estimates differ from scale weights or contamination exists.

A weighed batch moves one of three ways. When all its material has been processed into items, `IntakeStaff` or a `StoreManager` marks it sorted, moving it from `WEIGHED` to terminal `SORTED` (`ERR_BATCH_NOT_WEIGHED` from any other state). When a post-hoc hazard is discovered — including the job-level cascade of §3.4 — a `HazmatTechnician`, `StoreManager`, or `WarehouseAdmin` quarantines it, moving it from `WEIGHED` to `QUARANTINED` (same state gate, `ERR_BATCH_NOT_WEIGHED`): the job's certified tonnage is debited back by the batch's diverted pounds, and the open period report recomputes excluding the batch. A quarantined batch is then resolved one of two ways, each requiring the `QUARANTINED` state (`ERR_BATCH_NOT_QUARANTINED`). Resolving with an `outcome` of `REMEDIATED` returns the batch to `WEIGHED`; if the resolution supplies a `new_scale_weight_lbs` — which must be greater than zero and no less than the batch's recorded `contamination_weight_lbs`, else `ERR_INVALID_WEIGHTS` (HTTP 400) — the batch's `scale_weight_lbs` is replaced and `diverted_weight_lbs` recomputed from it, the job's certified tonnage is re-credited by the diverted pounds, and the open report recomputes including the batch — this weigh–quarantine–reweigh cycle is unbounded. Resolving with an `outcome` of `DISPOSE_HAZARD` lands the batch in terminal `DISPOSED_HAZARD`: its `diverted_weight_lbs` is set to 0, permanently excluding it from diversion, and its `scale_weight_lbs` routes to the period report's landfill accounting.

### 3.7. Item Intake and the Pricing Engine

Items are the sellable unit of the warehouse, and each arrives through one of three provenances. An `IntakeStaff` operator intakes an item naming its `category_id`, a `description_text`, a `condition_grade` of `A` through `D`, a `measure_qty` greater than zero expressed in a `measure_unit` of `UNIT`, `SQFT`, or `LINEAR_FT`, a `pre_1978_flag`, and an `estimated_weight_lbs` of at least zero used for walk-in diversion accounting. An item linked to a received donation offer names its `offer_id`; the offer must stand in `RECEIVED` (`ERR_INVALID_OFFER_STATE`) and the item's `category_id` must equal the offer's category (`ERR_CATEGORY_MISMATCH`). An item drawn from a salvage batch names its `batch_id`; the batch must stand `WEIGHED` or `SORTED` (`ERR_INVALID_BATCH_STATE`) and the batch's category must likewise match (`ERR_CATEGORY_MISMATCH`). Unlinked stock names neither. In every case the category must be `ACCEPTING` (`ERR_CATEGORY_NOT_ACCEPTING`). Items with hazmat exposure — the category carries `hazmat_risk_flag`, or the item's own `pre_1978_flag` is set — must be cleared before intake: an exposed item with no `batch_id` requires a `screening_id` naming a screening whose `outcome` is `CLEARED` (`ERR_HAZMAT_SCREENING_REQUIRED`), while batch-linked items inherit the job's screening and need none of their own. Every item is born with `pricing_status` `UNPRICED` and `sales_status` `BACKROOM`, a `markdown_step` of 0, `disposition_recommended` of `NONE`, and no `zone_id`, `floor_since`, `parent_item_id`, `price_override_cents`, or `sold_via_sale_id`; `days_on_floor` reads 0 while the item has never been placed. The catalog lists with filters on `category_id`, `batch_id`, `offer_id`, `zone_id`, `sold_via_sale_id`, `parent_item_id`, `screening_id`, `sales_status`, and `pricing_status`, and a `slow_only` flag that keeps only items whose `days_on_floor` has reached their category's `target_turn_days`.

A measured item too big to sell whole can be split. Splitting, by `IntakeStaff` or a `StoreManager`, requires the item to stand in `BACKROOM` (`ERR_ITEM_NOT_BACKROOM`) and takes a `split_qty` that must be greater than zero and strictly less than the item's `measure_qty`; a quantity outside those bounds — or any split of a `UNIT`-measured item — fails with `ERR_SPLIT_INVALID_QUANTITY`. The parent's `measure_qty` shrinks by the split quantity and its `pricing_status` reverts to `UNPRICED` so it is priced afresh, while a new remainder item is created with `measure_qty` equal to the split quantity and `parent_item_id` pointing back at the parent — a self-referential lineage of remainders. The remainder copies the parent's category, provenance links (`offer_id`, `batch_id`, `screening_id`), `description_text`, `condition_grade`, `pre_1978_flag`, and `estimated_weight_lbs` verbatim, and is born `UNPRICED` in `BACKROOM`.

Pricing is a `StoreManager` act that moves an item from `UNPRICED` to `PRICED` (from any other pricing state, `ERR_ITEM_NOT_UNPRICED`). When the manager supplies a `price_override_cents` greater than zero, that value becomes the `list_price_cents` verbatim and is recorded on the item. Otherwise the pricing engine runs. The base comes from the category's `pricing_model`: for `FLAT` the base is exactly the category's `base_rate_cents`; for `PER_UNIT`, `PER_SQFT`, or `PER_LINEAR_FT` the base is `base_rate_cents` multiplied by the item's `measure_qty`. The base is then multiplied by a condition factor — 1.00 for grade `A`, 0.75 for `B`, 0.50 for `C`, 0.25 for `D` — and by a hazardous-handling factor of 1.15 when the category's `hazmat_risk_flag` is set or the item's `pre_1978_flag` is true, 1.00 otherwise. The product is rounded half-up to integer cents, and the result is clamped from below at a minimum list price of one dollar (100 cents). Either way, pricing also initializes `current_price_cents` to the list price, resets `markdown_step` to 0, clears `disposition_recommended` to `NONE`, and records the manager's `X-User-ID` in `priced_by_user_id`. The pricing dimension runs in parallel to the sales-floor dimension: an item's `pricing_status` says nothing about where it physically stands, and vice versa.

### 3.8. The Sales Floor: Zones, Markdown Sweeps, and Disposition

The showroom is organized into `StoreZone` records, created by a `StoreManager` or `WarehouseAdmin` with a `code` unique across all zones (`ERR_DUPLICATE_CODE`), a `display_name`, a `capacity` of at least 1, an optional `allowed_category_id` restricting the zone to one category, and a `restock_threshold` that defaults to 0. A zone's `current_count` is derived, never set: it counts the items whose `zone_id` names the zone and whose `sales_status` is `ON_FLOOR` or `RESERVED` — a reserved item still occupies its slot. Whenever that count sits at or below the threshold, the zone's `restock_recommended` flag is true; the flag is recomputed on every occupancy change. Zones are born `OPEN`, can be closed to `CLOSED` and reopened by a manager or administrator, and closing a zone evicts nothing — resident items stay — but blocks new placements while it lasts. Shrinking a zone's `capacity` below its current occupancy is refused with `ERR_CAPACITY_BELOW_OCCUPANCY`. A zone update may also revise `restock_threshold` or `allowed_category_id` (a category reference that does not resolve fails with `ERR_CATEGORY_NOT_FOUND`). Zones list with filters on `status` or `allowed_category_id`.

Placing an item is a manager's decision with five gates: the item must stand in `BACKROOM` (`ERR_ITEM_NOT_BACKROOM`), it must be `PRICED` (`ERR_ITEM_NOT_PRICED`), the target zone must be `OPEN` (`ERR_ZONE_NOT_OPEN`), a zone with an `allowed_category_id` accepts only items of that category (`ERR_ZONE_CATEGORY_MISMATCH`), and a zone whose `current_count` already equals its `capacity` is full (`ERR_ZONE_AT_CAPACITY`). Placement lands the item `ON_FLOOR`, records the `zone_id`, stamps `floor_since` from the logical clock, raises the zone's count by one, and recomputes the restock flag — bumping the `version` of both item and zone. From then on the item's `days_on_floor` reads the whole days between `floor_since` and the logical clock. Unplacing reverses it exactly: the item returns to `BACKROOM` from `ON_FLOOR` (`ERR_ITEM_NOT_ON_FLOOR` otherwise), its `zone_id` and `floor_since` clear, the zone's count drops by one and its flag recomputes, and a place followed by an unplace leaves zone occupancy unchanged.

Stock that will never sell at list decays under a disciplined markdown program. A `StoreManager` executes a markdown sweep, optionally attaching `notes`; the run records the logical-clock date it evaluated against as `as_of_date` and counts its own work: `items_evaluated` is the number of items standing `PRICED` and `ON_FLOOR` at sweep time, `items_marked_down` the number whose `markdown_step` increased, and `items_flagged_disposition` the number whose `disposition_recommended` moved from `NONE` to their category's `slow_item_disposition`. An item is eligible when it is `PRICED`, `ON_FLOOR`, carries no disposition recommendation, and its `days_on_floor` is at least the category's `markdown_after_days` plus the item's current `markdown_step` times the category's `markdown_interval_days` — the comparison is inclusive, so an item standing exactly on the boundary day is marked down that day, not the day after. Eligible items are processed in ascending `floor_since` order, ties broken by ascending `created_at`. An item below its category's `max_markdown_steps` steps up by one, and its new `current_price_cents` is the `list_price_cents` multiplied by (1 − `markdown_step_pct`) raised to the power of the new step count, rounded half-up to integer cents — the exponent always applies to the list price, never to the previous current price — but never below the markdown floor, the `list_price_cents` multiplied by `floor_price_pct` and itself rounded half-up; the effective price is the larger of the two. An eligible item that has already reached `max_markdown_steps` is not marked down again; its `disposition_recommended` is set to the category's `slow_item_disposition` instead, flagging it for removal. Runs are kept for audit and can be listed or read back.

The end of the line is disposition. A manager or administrator disposes of an item standing in `BACKROOM` or `ON_FLOOR` — from any other sales-floor state the request fails with `ERR_ITEM_NOT_BACKROOM` — by naming a `disposition` of `DONATE`, `RECYCLE`, or `DISPOSE`, which lands the item in the matching terminal state — `DONATED_OUT`, `RECYCLED`, or `DISPOSED`. Disposing from the floor clears its `zone_id` and `floor_since`, drops the zone's count by one, and recomputes the restock flag; either way the `OPEN` period report recomputes its walk-in stream. The two remaining sales-floor states arise only through the register: adding an item to an open sale reserves it (`ON_FLOOR` → `RESERVED`), finalizing that sale sells it (`RESERVED` → `SOLD`, stamping `sold_via_sale_id` and clearing `zone_id` and `floor_since`), and voiding the sale reverses it (`SOLD` → `ON_FLOOR`, restored to the zone it occupied when reserved, with `floor_since` restamped to the void's clock time) — all narrated in §3.9.

### 3.9. Checkout, Trade Accounts, and Period Reconciliation

Sales come in two channels. A `Cashier`, a `StoreManager`, or a `Contractor` opens a sale with a `sale_channel` of `WALK_IN` or `CONTRACTOR_ACCOUNT`; the latter requires a `contractor_id` — which a `Contractor` caller must set to their own account's `id`, else `ERR_NOT_RESOURCE_OWNER` — while a walk-in leaves it null. A caller in the `Contractor` role may open only contractor-account sales naming their own account: a `Contractor` attempting a `WALK_IN` sale, or naming another account, is refused with `ERR_NOT_RESOURCE_OWNER`. A contractor-account sale may attach a bulk purchase agreement by `agreement_id`; the attached agreement must stand `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and the logical clock must lie inside its validity window (`ERR_AGREEMENT_NOT_IN_WINDOW`). Opening a contractor sale also requires the account to stand `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`). At creation the sale pins its `tier_snapshot` — the account's `discount_tier` as computed from the trailing volume excluding the sale being created — which is null for walk-ins; every sale starts `OPEN` with `subtotal_cents`, `bulk_discount_cents`, `tax_cents`, and `total_cents` at 0, `discount_pct_applied` at 0, `payment_amount_cents` at 0, and no `finalized_at` or `void_reason`. Sales list with filters on `contractor_id`, `agreement_id`, or `status`, and a contractor sees only their own.

Lines are added to an `OPEN` sale only (`ERR_SALE_NOT_OPEN`), each naming an `item_id` that must stand `ON_FLOOR` — reserving an item not on the floor fails with `ERR_ITEM_NOT_AVAILABLE`. Adding a line moves the item to `RESERVED` (it keeps occupying its zone slot), captures the item's `current_price_cents` into the line's `unit_price_cents` at that moment, and computes `line_total_cents` as the unit price multiplied by the line's `quantity`, rounded half-up to integer cents — per-line rounding happens before any subtotal summation, and summing first and rounding once is non-conformant. The `quantity` defaults to the item's full `measure_qty`; a partial quantity is accepted only for items measured in `SQFT` or `LINEAR_FT`, since `UNIT`-measured goods are taken whole. A non-positive quantity, or one exceeding the item's `measure_qty`, is rejected with `ERR_INVALID_REQUEST`. Removing a line from an `OPEN` sale deletes the record outright and returns the item to `ON_FLOOR` with its `zone_id` retained; lines can be listed filtered by `sale_id` or `item_id`, with a `Contractor` caller restricted to lines of their own sales — reading another sale's line fails with `ERR_NOT_RESOURCE_OWNER`.

Finalizing is the register's decisive act, open to the cashier, a manager, or the contractor who owns the sale. The sale must stand `OPEN` (`ERR_SALE_NOT_OPEN`) and hold at least one line (`ERR_EMPTY_SALE`). A contractor-channel sale re-checks that the account still stands `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), then faces the credit gate: an account with a `credit_limit_cents` of zero extends no credit, so if the outstanding balance plus this sale's total would exceed zero the finalize is refused with `ERR_CREDIT_LIMIT_EXCEEDED`; an account with a positive limit instead lets the finalize post and absorbs the breach through the auto-suspension cascade below. A walk-in sale must be paid: the recorded `payment_amount_cents` must at least cover the `total_cents` (`ERR_PAYMENT_INSUFFICIENT`). If an agreement is attached, it must still stand `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) and the clock must lie at or after the agreement's `valid_from` and strictly before its `valid_until` (else `ERR_AGREEMENT_NOT_IN_WINDOW`).

Totals then compute in a pinned order. The per-line totals are already rounded; `subtotal_cents` is their sum. The discount percentage `discount_pct_applied` is the larger of a tier percentage and an agreement percentage. The tier percentage reads the pinned `tier_snapshot`: `STANDARD` yields zero, `SILVER` yields five percent, `GOLD` yields ten percent — finalize must use the snapshot, never a freshly recomputed tier, so a tier change produced by this very sale applies only to future sales. The agreement percentage is the attached agreement's `discount_pct` when all of the following hold — the sale references an `agreement_id`, the agreement stands `ACTIVE`, the clock lies inside its validity window, and the sale's line quantities for items of the agreement's `category_id` sum to at least the agreement's `min_quantity` — and zero otherwise. `bulk_discount_cents` is the subtotal multiplied by that chosen percentage, rounded half-up; `tax_cents` is the subtotal minus the bulk discount, the difference multiplied by the seven percent sales-tax rate, rounded half-up; and `total_cents` is the subtotal minus the bulk discount plus the tax.

Finalization cascades outward in hops. Each line's item moves from `RESERVED` to `SOLD` with `sold_via_sale_id` set and its `zone_id` and `floor_since` cleared; each such item's former zone loses one from its `current_count` and recomputes `restock_recommended`. On the contractor channel the account's `outstanding_balance_cents` and `trailing_volume_cents` each gain the sale's `total_cents` and its `discount_tier` is recomputed; if the post-finalize balance now exceeds the `credit_limit_cents`, the account is suspended automatically with `suspension_reason` recorded as `CREDIT_LIMIT_BREACH` and every one of its `ACTIVE` agreements is cancelled. A qualifying agreement's `fulfilled_quantity` grows by the sale's qualifying line quantities. On the walk-in channel the `OPEN` diversion report for the finalize period recomputes its walk-in sold pounds. The finalize stamps `finalized_at` from the logical clock and bumps the `version` of the sale and, on the contractor channel, the account.

A finalized sale can be voided by a `StoreManager` or `WarehouseAdmin` with an optional `void_reason`, recorded when supplied; voiding from any state other than `FINALIZED` fails with `ERR_SALE_NOT_FINALIZED`. Voiding is a full compensation: every line item standing `SOLD` returns to `ON_FLOOR` in the zone it occupied when reserved, with `sold_via_sale_id` cleared and `floor_since` restamped to the void's clock time, each restored zone's count rises by one and its restock flag recomputes — so finalize followed by void leaves zone occupancy exactly unchanged. On the contractor channel the account's outstanding balance and trailing volume each lose the sale's total and the discount tier is recomputed, so finalize followed by void leaves the outstanding balance exactly unchanged; the attached agreement's `fulfilled_quantity` is decremented by this sale's qualifying quantities. An `OPEN` sale can instead be cancelled outright by the cashier, a manager, or the owning contractor, landing it in `CANCELLED` and un-reserving every line's item back to `ON_FLOOR`; cancelling from any other state fails with `ERR_SALE_NOT_OPEN`, and a contractor acting on a sale that is not theirs is refused with `ERR_NOT_RESOURCE_OWNER`.

Trade customers buy on account. A `WarehouseAdmin` registers a `ContractorAccount` with a `company_name`, a `contact_email`, a `credit_limit_cents` of at least zero, and `payment_terms_days` defaulting to 30 (and at least 1 when supplied); the account starts in `PENDING_APPROVAL` with `outstanding_balance_cents` and `trailing_volume_cents` at 0 and a `discount_tier` of `STANDARD`. Approval by an administrator moves the account to `ACTIVE` (from any other state, `ERR_INVALID_ACCOUNT_STATE`) and records who approved it in `approved_by_user_id`. The outstanding balance is ledger-synced: it is the sum of `total_cents` over the account's `FINALIZED` sales, minus payments, minus the totals of voided sales. The trailing volume is the sum of `total_cents` over the account's sales standing `FINALIZED` whose `finalized_at` falls inside the inclusive 365-day window ending at the logical clock, and the discount tier re-derives from it on every change with inclusive thresholds: at least $100,000 (10,000,000 cents) is `GOLD`, at least $25,000 (2,500,000 cents) is `SILVER`, and anything less is `STANDARD`. Accounts list with filters on `status` or `discount_tier`.

Standing can be lost two ways. An administrator suspends an `ACTIVE` account manually (from any other state, `ERR_ACCOUNT_NOT_ACTIVE`), recording a `suspension_reason`, and the suspension cascades: every bulk purchase agreement of the account standing `ACTIVE` is cancelled. The system also suspends on its own when a finalize pushes the post-finalize outstanding balance above the credit limit, recording `CREDIT_LIMIT_BREACH` as the reason and running the same agreement cascade. Reinstatement from `SUSPENDED` (from any other state, `ERR_INVALID_ACCOUNT_STATE`) requires the outstanding balance to sit at or below the credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`) and clears the `suspension_reason`. Closing an account is permitted only from `ACTIVE` or `SUSPENDED` (from any other state, `ERR_INVALID_ACCOUNT_STATE`) and requires an outstanding balance of exactly zero (`ERR_OUTSTANDING_BALANCE_NONZERO`), landing it in terminal `CLOSED`; closing an `ACTIVE` account cancels its `ACTIVE` agreements, while closing a `SUSPENDED` account needs no such cascade since suspension already ran it. Payments against the balance are recorded by an administrator as a positive `amount_cents` (a non-positive amount fails with `ERR_INVALID_REQUEST`); a payment exceeding the outstanding balance is refused with `ERR_OVERPAYMENT`, and a recorded payment reduces `outstanding_balance_cents`, bumps the account's `version`, and answers `201 Created` with the updated account.

Volume buyers negotiate terms per category. Creating a `BulkPurchaseAgreement` — an OCC-guarded create carrying the mandatory `expected_account_version` of §2.7 — names the `contractor_id`, the `category_id` the terms apply to, a fractional `discount_pct` such as 0.12, a `min_quantity` greater than zero expressed in the agreement's `quantity_unit` (`UNIT`, `SQFT`, or `LINEAR_FT`), and a validity window running from `valid_from` (inclusive) to `valid_until` (exclusive), whose end must be strictly after its start (`ERR_INVALID_TIME_WINDOW`). The create may name a `supersedes_agreement_id` referencing an `ACTIVE` agreement of the same contractor and category — anything else fails with `ERR_AGREEMENT_NOT_ACTIVE` — in which case the prior agreement moves to `SUPERSEDED`; the create bumps the account's `version` by one. New agreements stand `ACTIVE` and track a `fulfilled_quantity`, the cumulative qualifying quantity sold under them on finalized, non-voided sales, starting at 0. Expiry is lazy per §2.4: once the clock reaches `valid_until`, the agreement flips to `EXPIRED` on its next read or use. An administrator can cancel an `ACTIVE` agreement (any other state fails with `ERR_AGREEMENT_NOT_ACTIVE`), and suspension or closure of the account cancels its active agreements as a cascade. Agreements list with filters on `contractor_id`, `category_id`, `status`, or `supersedes_agreement_id`, with contractors reading only their own.

Everything the warehouse diverts rolls up monthly. A `WarehouseAdmin` opens a `DiversionReport` by naming its `period` in `YYYY-MM` form; one report per period, so a duplicate fails with `ERR_DUPLICATE_REPORT_PERIOD`. The report stands `OPEN` with `total_diverted_lbs`, `sold_lbs`, `donated_lbs`, `recycled_lbs`, and `landfill_lbs` all starting at 0, and while open it recomputes on every relevant event per the ledger principle of §2.9. Closing is an ops-run checkpoint by an administrator, gated three ways: the report must stand `OPEN` (`ERR_REPORT_NOT_OPEN`); no salvage batch anywhere may still stand `MANIFESTED`, because unweighed material has no `report_period` yet and cannot be attributed (`ERR_UNWEIGHED_BATCHES_IN_PERIOD`); and no batch of the report's period may stand `QUARANTINED` (`ERR_QUARANTINED_BATCHES_OPEN`). At close the five figures freeze: from the batch stream, certified diverted pounds are the sum of `diverted_weight_lbs` over batches whose `report_period` equals the period, standing `WEIGHED` or `SORTED`, in `divertible` categories, and batch landfill pounds are the sum of `contamination_weight_lbs` over the period's `WEIGHED` and `SORTED` batches plus the full `scale_weight_lbs` of the period's `DISPOSED_HAZARD` batches. From the walk-in stream — only items with no `batch_id`, so batch-derived goods are never double counted — each item contributes its `estimated_weight_lbs` to the period in which it reached its terminal state: a `SOLD` item attributes by its sale's `finalized_at`, while `DONATED_OUT`, `RECYCLED`, and `DISPOSED` items attribute by their disposition date. The frozen `sold_lbs` is the batch stream's certified diverted pounds — the reuse-store convention credits certified salvage tonnage to the retail stream until individual items prove otherwise — plus the walk-in weight of items sold in the period in `divertible` categories; `donated_lbs` and `recycled_lbs` are the walk-in weights of items donated out or recycled in the period in `divertible` categories; and `landfill_lbs` is the batch landfill plus the walk-in weight of items disposed in the period. The `total_diverted_lbs` is the sum of the sold, donated, and recycled figures. Closing stamps `closed_at` from the logical clock and records the administrator in `closed_by_user_id`; a `CLOSED` report never recomputes, whatever later happens in its period. Reports list with a filter on `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The one deletion in the API — removing a sale line — returns `204 No Content` with no resource payload. Request and response bodies for every operation are reconstructed from the narratives of §2 and §3; this table is deliberately minimal.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reuse/_clock/set_current_utc` | Advance the logical clock (test-driving) | WarehouseAdmin |
| POST | `/reuse/donors` | Register a donor | IntakeStaff, WarehouseAdmin |
| GET | `/reuse/donors` | List donors | IntakeStaff, WarehouseAdmin, StoreManager, CrewCoordinator |
| GET | `/reuse/donors/{donorId}` | Get one donor (Donor role restricted to own record) | IntakeStaff, WarehouseAdmin, Donor |
| PATCH | `/reuse/donors/{donorId}` | Update donor (activate/deactivate, contact details) | IntakeStaff, WarehouseAdmin |
| POST | `/reuse/categories` | Create a category (acceptance + pricing + markdown policy) | StoreManager, WarehouseAdmin |
| GET | `/reuse/categories` | List categories | StoreManager, WarehouseAdmin, IntakeStaff, Cashier, Contractor, CrewCoordinator |
| GET | `/reuse/categories/{categoryId}` | Get one category | StoreManager, WarehouseAdmin, IntakeStaff, Cashier, Contractor, CrewCoordinator |
| PATCH | `/reuse/categories/{categoryId}` | Update category policy / acceptance status | StoreManager, WarehouseAdmin |
| POST | `/reuse/donation-offers` | Create a donation offer | Donor, IntakeStaff |
| GET | `/reuse/donation-offers` | List offers (Donor role sees own only) | IntakeStaff, StoreManager, WarehouseAdmin, Donor |
| GET | `/reuse/donation-offers/{offerId}` | Get one offer (Donor role: own only) | IntakeStaff, StoreManager, WarehouseAdmin, Donor |
| POST | `/reuse/donation-offers/{offerId}/review` | Move an offer from OFFERED to UNDER_REVIEW | IntakeStaff |
| POST | `/reuse/donation-offers/{offerId}/request-info` | Move an offer from UNDER_REVIEW to NEEDS_INFO | IntakeStaff |
| POST | `/reuse/donation-offers/{offerId}/resubmit` | Resubmit a NEEDS_INFO offer back to UNDER_REVIEW | Donor, IntakeStaff |
| POST | `/reuse/donation-offers/{offerId}/accept` | Accept an offer; computes the guidance valuation | IntakeStaff |
| POST | `/reuse/donation-offers/{offerId}/reject` | Reject an offer under review | IntakeStaff |
| POST | `/reuse/donation-offers/{offerId}/receive` | Receive an accepted offer; records the receiver | IntakeStaff |
| POST | `/reuse/donation-offers/{offerId}/cancel` | Cancel an offer | Donor, IntakeStaff |
| POST | `/reuse/deconstruction-jobs` | Create a deconstruction job | CrewCoordinator, WarehouseAdmin |
| GET | `/reuse/deconstruction-jobs` | List jobs | CrewCoordinator, WarehouseAdmin, CrewLead, HazmatTechnician, IntakeStaff |
| GET | `/reuse/deconstruction-jobs/{jobId}` | Get one job | CrewCoordinator, WarehouseAdmin, CrewLead, HazmatTechnician, IntakeStaff |
| POST | `/reuse/deconstruction-jobs/{jobId}/request-screening` | Move a job from REQUESTED to SCREENING_PENDING | CrewCoordinator |
| POST | `/reuse/deconstruction-jobs/{jobId}/schedule` | Schedule a CLEARED job (lead + vehicle + window) | CrewCoordinator |
| POST | `/reuse/deconstruction-jobs/{jobId}/start` | Start a SCHEDULED job | CrewCoordinator, CrewLead |
| POST | `/reuse/deconstruction-jobs/{jobId}/complete` | Complete an IN_PROGRESS job | CrewCoordinator, CrewLead |
| POST | `/reuse/deconstruction-jobs/{jobId}/begin-remediation` | Move a HAZMAT_HOLD job into remediation | CrewCoordinator |
| POST | `/reuse/deconstruction-jobs/{jobId}/complete-remediation` | Return a remediating job to screening | CrewCoordinator |
| POST | `/reuse/deconstruction-jobs/{jobId}/cancel` | Cancel a non-terminal job; cascades to assignments, appointments, manifested batches | CrewCoordinator, WarehouseAdmin |
| POST | `/reuse/hazmat-screenings` | Record a hazmat screening; drives job CLEARED / HAZMAT_HOLD transitions | HazmatTechnician |
| GET | `/reuse/hazmat-screenings` | List screenings | HazmatTechnician, CrewCoordinator, WarehouseAdmin, IntakeStaff, StoreManager |
| GET | `/reuse/hazmat-screenings/{screeningId}` | Get one screening | HazmatTechnician, CrewCoordinator, WarehouseAdmin, IntakeStaff, StoreManager |
| POST | `/reuse/salvage-batches` | Manifest a salvage batch under a job | CrewLead, CrewCoordinator |
| GET | `/reuse/salvage-batches` | List batches | CrewLead, CrewCoordinator, IntakeStaff, StoreManager, WarehouseAdmin |
| GET | `/reuse/salvage-batches/{batchId}` | Get one batch | CrewLead, CrewCoordinator, IntakeStaff, StoreManager, WarehouseAdmin |
| POST | `/reuse/salvage-batches/{batchId}/weigh` | Weigh a manifested batch; computes diverted weight; cascades to job and period report | CrewLead, CrewCoordinator |
| POST | `/reuse/salvage-batches/{batchId}/quarantine` | Quarantine a weighed batch (post-hoc hazmat discovery) | HazmatTechnician, StoreManager, WarehouseAdmin |
| POST | `/reuse/salvage-batches/{batchId}/resolve-quarantine` | Resolve a quarantine as REMEDIATED or DISPOSE_HAZARD | HazmatTechnician, StoreManager, WarehouseAdmin |
| POST | `/reuse/salvage-batches/{batchId}/mark-sorted` | Mark a weighed batch fully sorted | IntakeStaff, StoreManager |
| POST | `/reuse/items` | Intake an item (walk-in offer, batch, or unlinked stock) | IntakeStaff |
| GET | `/reuse/items` | List/search items (including slow-stock filter) | IntakeStaff, StoreManager, Cashier, WarehouseAdmin, Contractor |
| GET | `/reuse/items/{itemId}` | Get one item | IntakeStaff, StoreManager, Cashier, WarehouseAdmin, Contractor |
| POST | `/reuse/items/{itemId}/price` | Price an item (engine or manager override) | StoreManager |
| POST | `/reuse/items/{itemId}/place` | Place a priced backroom item into a floor zone | StoreManager |
| POST | `/reuse/items/{itemId}/unplace` | Return a floor item to the backroom | StoreManager |
| POST | `/reuse/items/{itemId}/dispose` | Dispose of an item (donate out, recycle, dispose) | StoreManager, WarehouseAdmin |
| POST | `/reuse/items/{itemId}/split` | Split a measured item; creates a remainder child | IntakeStaff, StoreManager |
| POST | `/reuse/store-zones` | Create a store zone | StoreManager, WarehouseAdmin |
| GET | `/reuse/store-zones` | List zones | StoreManager, IntakeStaff, Cashier, WarehouseAdmin |
| GET | `/reuse/store-zones/{zoneId}` | Get one zone | StoreManager, IntakeStaff, Cashier, WarehouseAdmin |
| PATCH | `/reuse/store-zones/{zoneId}` | Update zone (open/close, capacity with occupancy floor) | StoreManager, WarehouseAdmin |
| POST | `/reuse/markdown-runs` | Execute a markdown sweep over priced on-floor items | StoreManager |
| GET | `/reuse/markdown-runs` | List markdown runs | StoreManager, WarehouseAdmin |
| GET | `/reuse/markdown-runs/{runId}` | Get one markdown run | StoreManager, WarehouseAdmin |

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reuse/contractor-accounts` | Create a contractor account (pending approval) | WarehouseAdmin |
| GET | `/reuse/contractor-accounts` | List contractor accounts | WarehouseAdmin, StoreManager, Cashier |
| GET | `/reuse/contractor-accounts/{accountId}` | Get one account (Contractor role: own only) | WarehouseAdmin, StoreManager, Cashier, Contractor |
| POST | `/reuse/contractor-accounts/{accountId}/approve` | Approve a pending account | WarehouseAdmin |
| POST | `/reuse/contractor-accounts/{accountId}/suspend` | Suspend an active account; cancels active agreements | WarehouseAdmin |
| POST | `/reuse/contractor-accounts/{accountId}/reinstate` | Reinstate a suspended account (balance within limit) | WarehouseAdmin |
| POST | `/reuse/contractor-accounts/{accountId}/close` | Close an account with zero balance | WarehouseAdmin |
| POST | `/reuse/contractor-accounts/{accountId}/payments` | Record a payment against the outstanding balance | WarehouseAdmin |
| POST | `/reuse/bulk-agreements` | Create a bulk agreement (OCC-guarded create-with-supersede) | WarehouseAdmin |
| GET | `/reuse/bulk-agreements` | List agreements (Contractor role: own only) | WarehouseAdmin, StoreManager, Contractor |
| GET | `/reuse/bulk-agreements/{agreementId}` | Get one agreement (Contractor role: own only) | WarehouseAdmin, StoreManager, Contractor |
| POST | `/reuse/bulk-agreements/{agreementId}/cancel` | Cancel an active agreement | WarehouseAdmin |
| POST | `/reuse/sales` | Open a sale (walk-in or contractor-account); captures the tier snapshot | Cashier, StoreManager, Contractor |
| GET | `/reuse/sales` | List sales (Contractor role: own only) | Cashier, StoreManager, WarehouseAdmin, Contractor |
| GET | `/reuse/sales/{saleId}` | Get one sale (Contractor role: own only) | Cashier, StoreManager, WarehouseAdmin, Contractor |
| POST | `/reuse/sales/{saleId}/lines` | Add a line; reserves an on-floor item | Cashier, StoreManager, Contractor |
| GET | `/reuse/sale-lines` | List sale lines (filter by sale or item) | Cashier, StoreManager, WarehouseAdmin, Contractor |
| GET | `/reuse/sale-lines/{lineId}` | Get one sale line | Cashier, StoreManager, WarehouseAdmin, Contractor |
| DELETE | `/reuse/sale-lines/{lineId}` | Remove a line from an open sale; un-reserves the item | Cashier, StoreManager, Contractor |
| POST | `/reuse/sales/{saleId}/finalize` | Finalize a sale; computes totals; cascades to items, zones, account standing | Cashier, StoreManager, Contractor |
| POST | `/reuse/sales/{saleId}/void` | Void a finalized sale; compensating restock and balance reversal | StoreManager, WarehouseAdmin |
| POST | `/reuse/sales/{saleId}/cancel` | Cancel an open sale; un-reserves its lines | Cashier, StoreManager, Contractor |
| POST | `/reuse/tax-receipts` | Draft a tax receipt for a received offer | IntakeStaff |
| GET | `/reuse/tax-receipts` | List receipts (Donor role: own only) | IntakeStaff, WarehouseAdmin, Donor |
| GET | `/reuse/tax-receipts/{receiptId}` | Get one receipt (Donor role: own only) | IntakeStaff, WarehouseAdmin, Donor |
| POST | `/reuse/tax-receipts/{receiptId}/issue` | Issue a draft receipt; final valuation; segregation of duties | IntakeStaff |
| POST | `/reuse/tax-receipts/{receiptId}/request-void` | Request a void on an issued receipt | IntakeStaff |
| POST | `/reuse/tax-receipts/{receiptId}/confirm-void` | Confirm a void; offer reverts to received | WarehouseAdmin |
| POST | `/reuse/tax-receipts/{receiptId}/reject-void` | Reject a void request; receipt returns to issued | WarehouseAdmin |
| POST | `/reuse/tax-receipts/{receiptId}/amend` | Amend an issued receipt (OCC on the receipt version); creates the replacement | IntakeStaff |
| POST | `/reuse/crew-members` | Register a crew member (volunteer or paid) | CrewCoordinator, WarehouseAdmin |
| GET | `/reuse/crew-members` | List crew members | CrewCoordinator, WarehouseAdmin, CrewLead, HazmatTechnician, IntakeStaff |
| GET | `/reuse/crew-members/{memberId}` | Get one crew member | CrewCoordinator, WarehouseAdmin, CrewLead, HazmatTechnician, IntakeStaff |
| PATCH | `/reuse/crew-members/{memberId}` | Update crew member (activate/deactivate, certifications, rate) | CrewCoordinator, WarehouseAdmin |
| POST | `/reuse/crew-assignments` | Assign crew to a job window | CrewCoordinator |
| GET | `/reuse/crew-assignments` | List assignments | CrewCoordinator, WarehouseAdmin, CrewLead, HazmatTechnician |
| GET | `/reuse/crew-assignments/{assignmentId}` | Get one assignment | CrewCoordinator, WarehouseAdmin, CrewLead, HazmatTechnician |
| POST | `/reuse/crew-assignments/{assignmentId}/complete` | Complete an assignment; records hours; recomputes the job fee | CrewCoordinator |
| POST | `/reuse/crew-assignments/{assignmentId}/cancel` | Cancel an assignment | CrewCoordinator |
| POST | `/reuse/crew-assignments/{assignmentId}/mark-no-show` | Mark an assignment as a no-show | CrewCoordinator |
| POST | `/reuse/vehicles` | Register a fleet vehicle | CrewCoordinator, WarehouseAdmin |
| GET | `/reuse/vehicles` | List vehicles | CrewCoordinator, WarehouseAdmin, IntakeStaff |
| GET | `/reuse/vehicles/{vehicleId}` | Get one vehicle | CrewCoordinator, WarehouseAdmin, IntakeStaff |
| PATCH | `/reuse/vehicles/{vehicleId}` | Update vehicle status (available / maintenance / retired) | CrewCoordinator, WarehouseAdmin |
| POST | `/reuse/pickup-appointments` | Book a pickup appointment on a vehicle; fee from donor tier | CrewCoordinator, IntakeStaff |
| GET | `/reuse/pickup-appointments` | List appointments | CrewCoordinator, IntakeStaff, WarehouseAdmin |
| GET | `/reuse/pickup-appointments/{appointmentId}` | Get one appointment | CrewCoordinator, IntakeStaff, WarehouseAdmin |
| POST | `/reuse/pickup-appointments/{appointmentId}/complete` | Complete a booked appointment | CrewCoordinator, IntakeStaff |
| POST | `/reuse/pickup-appointments/{appointmentId}/cancel` | Cancel a booked appointment | CrewCoordinator, IntakeStaff |
| POST | `/reuse/pickup-appointments/{appointmentId}/mark-no-show` | Mark a booked appointment as a no-show | CrewCoordinator, IntakeStaff |
| POST | `/reuse/diversion-reports` | Open a diversion reporting period | WarehouseAdmin |
| GET | `/reuse/diversion-reports` | List diversion reports | WarehouseAdmin, StoreManager |
| GET | `/reuse/diversion-reports/{reportId}` | Get one diversion report | WarehouseAdmin, StoreManager |
| POST | `/reuse/diversion-reports/{reportId}/close` | Close a period; freezes totals | WarehouseAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_WINDOW` | 400 Bad Request |
| `ERR_INVALID_WEIGHTS` | 400 Bad Request |
| `ERR_DONOR_NOT_FOUND` | 404 Not Found |
| `ERR_CATEGORY_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_SCREENING_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_RECEIPT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_OFFER_STATE` | 409 Conflict |
| `ERR_OFFER_NOT_ACCEPTED` | 409 Conflict |
| `ERR_OFFER_NOT_RECEIVABLE_SOURCE` | 409 Conflict |
| `ERR_INVALID_JOB_STATE` | 409 Conflict |
| `ERR_JOB_NOT_CLEARED` | 409 Conflict |
| `ERR_JOB_NOT_SCHEDULED` | 409 Conflict |
| `ERR_JOB_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_JOB_NOT_IN_HAZMAT_HOLD` | 409 Conflict |
| `ERR_JOB_NOT_REMEDIATING` | 409 Conflict |
| `ERR_BATCH_NOT_WEIGHABLE` | 409 Conflict |
| `ERR_BATCH_NOT_WEIGHED` | 409 Conflict |
| `ERR_BATCH_NOT_QUARANTINED` | 409 Conflict |
| `ERR_INVALID_BATCH_STATE` | 409 Conflict |
| `ERR_ITEM_NOT_UNPRICED` | 409 Conflict |
| `ERR_ITEM_NOT_PRICED` | 409 Conflict |
| `ERR_ITEM_NOT_BACKROOM` | 409 Conflict |
| `ERR_ITEM_NOT_ON_FLOOR` | 409 Conflict |
| `ERR_ITEM_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SALE_NOT_OPEN` | 409 Conflict |
| `ERR_SALE_NOT_FINALIZED` | 409 Conflict |
| `ERR_EMPTY_SALE` | 409 Conflict |
| `ERR_INVALID_ACCOUNT_STATE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_RECEIPT_NOT_DRAFT` | 409 Conflict |
| `ERR_RECEIPT_NOT_ISSUED` | 409 Conflict |
| `ERR_RECEIPT_NOT_VOID_REQUESTED` | 409 Conflict |
| `ERR_ZONE_NOT_OPEN` | 409 Conflict |
| `ERR_REPORT_NOT_OPEN` | 409 Conflict |
| `ERR_UNWEIGHED_BATCHES_IN_PERIOD` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 Conflict |
| `ERR_VEHICLE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_HAZMAT_SCREENING_REQUIRED` | 422 Unprocessable Content |
| `ERR_QUARANTINED_BATCHES_OPEN` | 422 Unprocessable Content |
| `ERR_SCREENER_CANNOT_LEAD` | 403 Forbidden |
| `ERR_RECEIPT_ISSUER_IS_RECEIVER` | 403 Forbidden |
| `ERR_CATEGORY_NOT_ACCEPTING` | 409 Conflict |
| `ERR_CONDITION_BELOW_ACCEPTANCE` | 422 Unprocessable Content |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 Conflict |
| `ERR_CREW_TIME_OVERLAP` | 409 Conflict |
| `ERR_VEHICLE_TIME_OVERLAP` | 409 Conflict |
| `ERR_ZONE_AT_CAPACITY` | 409 Conflict |
| `ERR_ZONE_CATEGORY_MISMATCH` | 409 Conflict |
| `ERR_CAPACITY_BELOW_OCCUPANCY` | 409 Conflict |
| `ERR_CERTIFICATION_MISMATCH` | 422 Unprocessable Content |
| `ERR_ACTIVE_APPOINTMENT_EXISTS` | 409 Conflict |
| `ERR_JOB_HAS_WEIGHED_BATCHES` | 409 Conflict |
| `ERR_NO_CREW_ASSIGNED` | 409 Conflict |
| `ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW` | 422 Unprocessable Content |
| `ERR_AGREEMENT_NOT_IN_WINDOW` | 422 Unprocessable Content |
| `ERR_SPLIT_INVALID_QUANTITY` | 422 Unprocessable Content |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_INSUFFICIENT` | 402 Payment Required |
| `ERR_OVERPAYMENT` | 402 Payment Required |
| `ERR_OUTSTANDING_BALANCE_NONZERO` | 402 Payment Required |
| `ERR_APPRAISAL_REQUIRED` | 422 Unprocessable Content |
| `ERR_ACTIVE_RECEIPT_EXISTS` | 409 Conflict |
| `ERR_CATEGORY_MISMATCH` | 422 Unprocessable Content |
| `ERR_JOB_CANCELLED` | 409 Conflict |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_RECEIPT_VERSION` | 412 Precondition Failed |
