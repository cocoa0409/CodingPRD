# Stormwater Billing API — Product Requirements Document

## 1. Introduction

Municipal stormwater utilities recover the cost of drainage infrastructure from the properties that generate runoff. Because runoff is driven by hard surfaces rather than water consumption, the fair unit of billing is a parcel's **impervious area** — the roofs, driveways, and paved lots that shed rainwater into the public system. This document specifies the backend service that turns field measurements of impervious area into recurring charges, administers the credits and exemptions that reduce those charges, and reconciles the money collected into the municipality's capital and operating funds.

The platform is organized around a small number of peer resources — accounts, parcels, measurements, exemptions, best-management-practice credits, inspections, bills, appeals, payments, and fund-ledger entries — that reference one another by identifier. A parcel's billable size is expressed in **Equivalent Residential Units (ERU)**, derived from its most recent authoritative measurement and any granted exemption. A tiered rate schedule converts ERU into an annual fee; provisional pollution-control credits discount that fee subject to later physical inspection; and a periodic operations cycle marks overdue bills delinquent and expires credits whose inspections have lapsed. Every mutation that changes a parcel's size, credit, or exemption re-derives the downstream fee so that a read of any resource always reflects the current state of the world.

The service is used by five distinct actors whose duties are deliberately separated: assessors who measure and register, credit inspectors who verify pollution controls, billing clerks who issue bills and move money, stormwater administrators who adjudicate disputes, and property owners who view and pay their own charges. Correctness of the monetary arithmetic, faithful ordering of validation checks, and strict segregation of who may collect versus who may reverse a payment are the primary engineering concerns.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well formed but the named role is not permitted to perform the requested operation under the access matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `PropertyOwner`, `Assessor`, `BillingClerk`, `CreditInspector`, and `StormwaterAdmin`.

When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting `Account`; that principal is an account holder who may view and pay only their own bills and file requests only against their own parcels. Ownership is enforced by comparing the `account_id` of the target resource — for a parcel, bill, appeal, payment, BMP credit, or exemption, the account it ultimately belongs to — against `X-User-ID`. When a `PropertyOwner` acts on a resource whose owning account is not their own, the request is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

When `X-User-Role` is `Assessor`, `BillingClerk`, `CreditInspector`, or `StormwaterAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a workflow calls for provenance — an assessor's identifier is stored as `recorded_by_user_id` on the measurement they record, a payment creator's identifier as `created_by_user_id` on the payment, and an appellant's identifier as `filed_by_user_id` on an appeal — but it is never compared against any entity's `id` for ownership. These four staff roles are not subject to the `PropertyOwner` ownership check.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may not be negative. Results are always returned in ascending order of `created_at` — that is, oldest first. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the number of records matching the filter before pagination and `has_more` is true when records remain beyond the returned page.

### 2.4. Resource Identity, Versioning, and the Logical Clock

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits at the moment of creation. Most resources — accounts, parcels, measurements, exemptions, BMP credits, inspections, bills, appeals, and payments — additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on each mutation. The `FundLedgerEntry` resource is the sole exception: it is an immutable audit record and carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field.

All time-dependent behavior is evaluated against a server-controlled **logical clock**, never the real wall clock. Before any request sets it, the logical clock reads `2026-03-01T00:00:00Z`. An operator may advance the clock to a supplied instant for test-driving; doing so returns the new `current_utc` but does not by itself re-evaluate delinquency or credit expiry — those are driven by the billing cycle described in Section 3.8.

### 2.5. Monetary Precision and Rounding

All money is represented as integer cents. Wherever a monetary figure is derived by multiplication — a tiered fee, a credit amount, a fund share, a delinquency penalty — the result is rounded to a whole number of cents using **round half up** (a value ending in exactly half a cent rounds away from zero to the next cent). Two rounding-order rules are fixed because they change the last cent:

- When the tiered base fee is computed from multiple ERU bands, the per-band products are summed first and the single sum is rounded once — never round each band and then add.
- When an applied payment is split between the two municipal funds, the capital share is rounded and the operating share is then taken as the applied amount minus the rounded capital share, so the two shares always add back to exactly the amount applied.

ERU is the one non-cent quantity that is rounded: `billable_eru` is rounded to one decimal place — the nearest tenth of an ERU — again using round half up.

### 2.6. Derived-Field Reconciliation

Several fields are computed rather than supplied, and the system keeps them consistent immediately after every change to their inputs. On a parcel, `impervious_area_sqft`, `exempt_pct`, `billable_eru`, and `current_fee_cents` are all derived: `impervious_area_sqft` mirrors the measured area of the parcel's currently `ACTIVE` measurement (0 when none exists), `exempt_pct` mirrors the granted fraction of the parcel's `GRANTED` exemption (0 when none), `billable_eru` is re-derived from those two inputs, and `current_fee_cents` holds the parcel's live marginal-variant annual fee for its present state — the tiered marginal base fee net of any active credit, and excluding the per-bill fixed administrative charge (which is a bill-issuance charge added only when a bill is cut, never a parcel attribute). `active_measurement_id` points at the identifier of that `ACTIVE` measurement, or is null when the parcel has none. Any event that records a new measurement, grants or denies an exemption, or changes a credit re-derives all of these in the same request.

On an account, `outstanding_balance_cents` is the sum, over that account's non-`VOID` bills, of each bill's `net_fee_cents` minus its `amount_paid_cents`; it is recomputed on any bill or payment mutation that touches the account. The account's `delinquency_status` is likewise recomputed on payment and during the billing cycle, as described in Section 3.8. On a bill, `assessed_fee_cents`, `net_fee_cents`, and `amount_paid_cents` are all derived from the bill's fee components and its applied payments.

### 2.7. Optimistic Concurrency on Parcel Re-derivation

Recording a new impervious measurement supersedes the parcel's current `ACTIVE` measurement and re-derives the parcel's ERU and fee off the new baseline. Because that operation is sensitive to any concurrent re-derivation of the same parcel, it is guarded by optimistic concurrency: the request must include `expected_parcel_version`, carrying the `version` of the target parcel that the client last observed. If the parcel's `version` has advanced since then — because another measurement was recorded, or an exemption decision or credit change re-derived the parcel — the client's view is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the only endpoint that takes a version field; no other write requires one.

### 2.8. Validation Ordering and Nested Retrieval

When several conditions could reject a request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. Authentication is checked first: the presence and validity of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`). Role authorization against the access matrix follows (`ERR_UNAUTHORIZED`). For a `PropertyOwner`, resource ownership is checked next (`ERR_FORBIDDEN_OWNERSHIP`). Existence is then verified — every path identifier and every foreign-key field in the body must reference a resource that exists, validated from left to right along the path, and the first missing reference yields `ERR_NOT_FOUND`. Only after those pass does the system check that all required body fields are present (`ERR_MISSING_FIELD`), that enum and numeric values are in range (`ERR_OUT_OF_RANGE`), then state legality, concurrency, referential-integrity, uniqueness, temporal, and fiscal rules in the order their sections describe. The specific business rules and the errors they raise are introduced alongside the workflows they guard in Section 3.

## 3. Business Logic & Workflows

### 3.1. Accounts and Parcel Registration

An `Assessor` or a `StormwaterAdmin` opens a property account by supplying the owner's details: `owner_name`, `contact_email`, an optional `billing_method`, and an optional `mailing_address`. The `billing_method` records where the stormwater charge is placed and must be either `TAX_ROLL` or `UTILITY_BILL`; when it is omitted, the account defaults to `UTILITY_BILL`. A newly opened account carries no debt — its `outstanding_balance_cents` starts at 0 and its `delinquency_status` starts at `CURRENT`. The `mailing_address` is the postal address used for tax-roll billing.

With an account in hand, an `Assessor` or `StormwaterAdmin` registers a parcel by naming its owning `account_id`, its assessor `parcel_number`, and its `land_use`. The `parcel_number` must be unique across every parcel in the system; an attempt to register a second parcel with an existing `parcel_number` is rejected with `ERR_DUPLICATE_PARCEL`. The `land_use` classifies the parcel as one of `RESIDENTIAL_SF`, `RESIDENTIAL_MF`, `COMMERCIAL`, `INDUSTRIAL`, `INSTITUTIONAL`, or `UNDEVELOPED`. A freshly registered parcel begins in the `DRAFT` state with a `billable_eru` of 0; it has no measurement, no exemption, and no fee until an assessor measures it. Parcels can be fetched individually — returning their computed ERU and fee — or listed with optional filters on `account_id` and `status`.

### 3.2. Impervious Measurement and ERU Assessment

Only an `Assessor` records an authoritative measurement of a parcel's impervious surface. The request names the `parcel_id`, the `measured_sqft` observed, the `method` used, an optional `source`, and the `expected_parcel_version` described in Section 2.7. The `measured_sqft` is the impervious area in square feet and must be zero or greater; a negative area is rejected with `ERR_OUT_OF_RANGE`, as is a `method` outside the set `GIS`, `FIELD_SURVEY`, and `AERIAL`. The `source` marks the measurement as either a `ROUTINE` assessment or an `APPEAL_REMEASURE` driven by an open appeal; when omitted it defaults to `ROUTINE`. The identifier of the acting assessor is captured as `recorded_by_user_id`.

Recording a measurement is a create-with-supersede operation carried out in a single request: the new measurement is written with `status` `ACTIVE`, and if the parcel already had an `ACTIVE` measurement, that prior one is moved to `SUPERSEDED` at the same time. The first measurement a parcel ever receives advances the parcel from `DRAFT` to `ACTIVE`. In every case the parcel's `active_measurement_id` and `impervious_area_sqft` are set from the new measurement, `billable_eru` and `current_fee_cents` are re-derived, and the parcel's `version` is incremented by one.

The parcel's billable size is expressed in **Equivalent Residential Units** and computed in a pinned order. First the exemption is applied to area: the impervious area is multiplied by one minus the parcel's exempt fraction. That exempt-adjusted area is then divided by the base area of a single residential unit — 3,000 square feet — to yield a raw ERU figure. Finally the raw figure is rounded to the nearest tenth of an ERU using round half up to produce `billable_eru`. The order matters: applying the exemption to area before dividing and rounding can differ, at the tenth-of-an-ERU boundary, from rounding first and exempting after, so exemption-to-area-then-divide-then-round is the required sequence. A parcel with no granted exemption uses an exempt fraction of 0, so its exempt-adjusted area equals its measured area.

### 3.3. Exemptions

A `PropertyOwner` (acting on their own parcel), an `Assessor`, or a `StormwaterAdmin` files an exemption request against a parcel by supplying the `parcel_id`, an exemption `category`, the `requested_pct`, and an optional `decision_note`. The `category` must be one of `GOVERNMENT`, `RELIGIOUS`, `AGRICULTURAL`, `UNDEVELOPED`, or `LOW_IMPACT`. The `requested_pct` is the fraction of impervious area the applicant asks to have exempted and must lie between 0 and 1 inclusive; a value outside that range is rejected with `ERR_OUT_OF_RANGE`. A new exemption is created in the `REQUESTED` state with a `granted_pct` of 0. Exemptions may be fetched individually or listed by `parcel_id` and `status`.

An `Assessor` or `StormwaterAdmin` decides a pending exemption by supplying an `outcome` together with an optional `granted_pct` and optional `decision_note`. A decision is only valid while the exemption is still `REQUESTED`; deciding one that is already `GRANTED` or `DENIED` is rejected with `ERR_INVALID_STATE`. When the outcome grants the exemption, the exemption moves from `REQUESTED` to `GRANTED`: its `granted_pct` is set to the `granted_pct` supplied on the decision, or to the original `requested_pct` when the decision omits one. A parcel may hold only one granted exemption at a time — if the parcel already has another `GRANTED` exemption, the grant is rejected with `ERR_INVALID_STATE`. Granting sets the parcel's `exempt_pct` to the granted fraction, re-derives the parcel's `billable_eru` and `current_fee_cents` from the new exemption, and increments the parcel's `version` by one. When the outcome denies the exemption instead, it moves from `REQUESTED` to `DENIED`, the `decision_note` is recorded, and the parcel is left unchanged.

### 3.4. BMP Credits and Their Inspection

Property owners install best-management practices — rain gardens, detention ponds, and the like — that reduce runoff, and the utility rewards them with a fee credit. A `PropertyOwner` (on their own parcel) or an `Assessor` creates a provisional credit by supplying the `parcel_id`, the `bmp_type`, a `self_reported_score`, an `effective_date`, and an `expiry_date`. The `bmp_type` must be one of `RAIN_GARDEN`, `DETENTION_POND`, `PERMEABLE_PAVEMENT`, `GREEN_ROOF`, or `CISTERN`. The `self_reported_score` is the owner's own performance rating and must lie between 0 and 100 inclusive; a score outside that range is rejected with `ERR_OUT_OF_RANGE`. Because a granted exemption already waives the parcel's fee, a credit may not be created on a parcel that holds a `GRANTED` exemption; such an attempt is rejected with `ERR_PARCEL_EXEMPT`.

The credit's coverage window runs from `effective_date` inclusive to `expiry_date` exclusive — the half-open interval that starts on the effective date and ends the instant before the expiry date. The `effective_date` must fall strictly before the `expiry_date`; otherwise the request is rejected with `ERR_INVALID_PERIOD`. A new credit window may not overlap the window of an existing `ACTIVE` credit of the same `bmp_type` on the same parcel; because the window is half-open, two windows that merely touch at an endpoint do not conflict, but any genuine overlap is rejected with `ERR_CREDIT_WINDOW_OVERLAP`.

A new credit is created `ACTIVE`. Its provisional `credit_pct` is derived from the self-reported score: the score is divided by 100 to yield a fraction, that fraction is multiplied by the credit scale of 0.60, and the result is capped at the maximum credit of 0.50 — that is, the provisional credit fraction is the smaller of 0.50 and six-tenths of the score expressed as a fraction of 100. The `inspected_score` stays null until an inspection completes. At creation the credit's re-inspection deadline, `next_inspection_due`, is set to the `effective_date` plus 365 days. Creating the credit re-derives the parcel's `current_fee_cents` and increments the parcel's `version` by one. Credits may be fetched individually or listed by `parcel_id` and `status`.

A `CreditInspector` schedules a physical inspection of a credit by naming the `bmp_credit_id`, a `scheduled_date`, and an optional `inspector_note`. The inspection is created in the `SCHEDULED` state. Inspections may be fetched individually or listed by `bmp_credit_id` and `status`. The same inspector later records the outcome by supplying a `result`, an `observed_score`, and an optional `inspector_note`. The `observed_score` is the field-verified rating between 0 and 100 inclusive; a value out of that range is rejected with `ERR_OUT_OF_RANGE`, as is a `result` that is neither `PASS` nor `FAIL`. Completing an inspection is only valid while it is still `SCHEDULED`; completing one that is already `COMPLETED` is rejected with `ERR_INSPECTION_ALREADY_COMPLETED`. The credit being inspected must itself be `ACTIVE` — a `REVOKED` or `EXPIRED` credit cannot be inspected, and an attempt to complete against such a credit is rejected with `ERR_INVALID_STATE`.

Completing the inspection sets its `status` to `COMPLETED` and stores the `result` and `observed_score`. The outcome then drives the credit. On a `PASS`, the credit stays `ACTIVE` but is re-scored: its `inspected_score` is set to the observed score, and its `credit_pct` is recomputed from the inspected score by the same formula used at creation — the inspected score divided by 100, multiplied by the credit scale of 0.60, capped at the maximum credit of 0.50 — after which the parcel's `current_fee_cents` is recomputed and the parcel's `version` is incremented by one. On a `FAIL`, the credit transitions from `ACTIVE` to `REVOKED`: its `inspected_score` is set to the observed score, its `credit_pct` is set to 0, the parcel's `current_fee_cents` is recomputed with the credit removed, and the parcel's `version` is incremented by one.

### 3.5. Issuing Bills and Computing the Fee

A `BillingClerk` issues a stormwater bill against a parcel by supplying the `parcel_id`, the `account_id` to charge, a `period_start`, a `period_end`, a `due_date`, and an optional `fee_variant`. The billing period runs from `period_start` to `period_end` as a closed interval that includes both endpoints, and the `due_date` is the date the payment falls due and drives delinquency. The `period_start` must not fall after the `period_end`; otherwise the request is rejected with `ERR_INVALID_PERIOD`. The `account_id` on the bill must equal the parcel's owning account; a mismatch is rejected with `ERR_ACCOUNT_PARCEL_MISMATCH`. A bill may be issued only for a parcel that is `ACTIVE` — one that has an `ACTIVE` measurement — and issuing against a `DRAFT` parcel is rejected with `ERR_INVALID_STATE`. The new bill's period may not overlap any non-`VOID` bill already on the same parcel; because the bill period is a closed interval, two periods that share even a single endpoint day conflict, and the overlap is rejected with `ERR_BILL_PERIOD_OVERLAP`.

At issuance the bill snapshots the parcel's current billable size into `eru_snapshot` from `billable_eru`, and computes its fee components. The `fee_variant` selects the fee algorithm and must be either `MARGINAL` or `FLAT`, defaulting to `MARGINAL` when omitted. The tiered creditable fee is written to `base_fee_cents`, a flat per-bill administrative charge of 500 cents is written to `fixed_charge_cents`, and the credit discount is written to `credit_amount_cents`. A newly issued bill is `ISSUED`, its `penalty_cents` is 0, and its `amount_paid_cents` is 0. Issuing the bill recomputes the charged account's `outstanding_balance_cents`. Bills may be fetched individually or listed by `parcel_id`, `account_id`, and `status`.

The tiered fee is computed over the parcel's ERU across three bands. The first band covers ERU above 0 up to and including 1.0 and is priced at 4,000 cents per ERU; the second band covers ERU above 1.0 up to and including 5.0 and is priced at 3,500 cents per ERU; the third band covers all ERU above 5.0 and is priced at 3,000 cents per ERU. Under the `MARGINAL` variant — the default — each band is charged at its own rate: the portion of ERU falling in the first band (the ERU capped at 1.0), plus the portion in the second band (the ERU capped at 5.0 less 1.0, but never below 0), plus the portion in the third band (the ERU less 5.0, but never below 0), each multiplied by that band's rate, and the three products summed and then rounded once to whole cents. Under the `FLAT` variant, the entire ERU is charged at the single rate of the tier the total ERU falls into: 4,000 cents per ERU when the ERU is at most 1.0, 3,500 cents per ERU when the ERU is at most 5.0, and 3,000 cents per ERU when the ERU exceeds 5.0. Note the tier edge is decided by "at most," so an ERU of exactly 5.0 is priced in the second tier at 3,500 cents per ERU; the flat figure is the ERU multiplied by that single rate and then rounded to whole cents. The flat and marginal figures agree only when ERU is at most 1.0 and diverge whenever ERU exceeds 1.0.

Once the base fee is known, the credit discount applies only to that creditable base and never to the fixed administrative charge: `credit_amount_cents` is the base fee multiplied by the parcel's active credit fraction, rounded to whole cents, and is 0 when the parcel has no `ACTIVE` credit. The `assessed_fee_cents` is then the fixed charge plus the base fee minus the credit amount. The `net_fee_cents` — the total owed — is the assessed fee plus any `penalty_cents`. Any authorized reader may also request a fee quote for a parcel without issuing a bill; the quote returns the parcel's `billable_eru` and active `credit_pct`, both fee variants' base fees as `base_fee_marginal_cents` and `base_fee_flat_cents`, and the corresponding assessed totals as `marginal_assessed_cents` and `flat_assessed_cents`, so the two variants can be compared before a bill is cut.

### 3.6. Payments and Fund Allocation

A `PropertyOwner` (paying their own bill) or a `BillingClerk` records a payment by supplying the `bill_id`, the paying `account_id`, an `amount_cents`, and a payment `method`. The `amount_cents` must be strictly greater than 0, and the `method` must be one of `ACH`, `CARD`, `CHECK`, or `TAX_ROLL`; a non-positive amount or an out-of-set method is rejected with `ERR_OUT_OF_RANGE`. The paying `account_id` must equal the bill's account; a mismatch is rejected with `ERR_ACCOUNT_PARCEL_MISMATCH`. A payment may only be applied to a payable bill — one whose status is `ISSUED`, `PARTIALLY_PAID`, or `DELINQUENT`; a bill that is `VOID`, `PAID`, or `ADJUSTED` is not payable, and a payment against it is rejected with `ERR_BILL_NOT_PAYABLE`. Overpayment is refused up front: the `amount_cents` may not exceed the bill's current outstanding, defined as `net_fee_cents` minus `amount_paid_cents`, and an amount that exceeds it is rejected with `ERR_OVERPAYMENT`. Because overpayment is refused, the `applied_amount_cents` recorded on the payment always equals the `amount_cents` submitted.

A recorded payment is created `APPLIED` and its `created_by_user_id` is set to the acting principal. Applying it adds the applied amount to the bill's `amount_paid_cents` and advances the bill's status: a bill moves from `ISSUED` or `DELINQUENT` to `PARTIALLY_PAID` when the cumulative amount paid is greater than 0 but still less than `net_fee_cents`, and to `PAID` when the cumulative amount paid equals `net_fee_cents`; a bill already `PARTIALLY_PAID` moves to `PAID` when its cumulative amount paid reaches `net_fee_cents`. Each payment recomputes the charged account's `outstanding_balance_cents` and its `delinquency_status`.

Every applied payment is split between two municipal funds and recorded as two `FundLedgerEntry` rows. The capital share is 30 percent of the applied amount, rounded to whole cents; the operating share is the applied amount minus that rounded capital share, so the two always sum to exactly the amount applied. The payment therefore writes one `ALLOCATION` entry to the `CAPITAL` fund and one `ALLOCATION` entry to the `OPERATING` fund, each recording the `source_payment_id`, its `fund`, the positive `amount_cents` moved, and an `entry_type` of `ALLOCATION`. Fund-ledger entries are read-only and may be fetched individually or listed by `source_payment_id` and `fund`.

A `BillingClerk` may refund an applied payment. Segregation of duties is strict: the principal refunding a payment must not be the one who created it, so a refund whose `X-User-ID` equals the payment's `created_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. A refund is only valid while the payment is `APPLIED`; refunding one that is already `REFUNDED` is rejected with `ERR_INVALID_STATE`. Refunding moves the payment from `APPLIED` to `REFUNDED`, subtracts the applied amount back out of the bill's `amount_paid_cents`, and recomputes the bill's status — a bill that had reached `PAID` or `PARTIALLY_PAID` falls back toward `ISSUED` as its paid total drops. The charged account's `outstanding_balance_cents` and `delinquency_status` are recomputed. Finally, the refund writes two `FundLedgerEntry` rows of `entry_type` `REVERSAL`, one against the `CAPITAL` fund and one against the `OPERATING` fund, equal and opposite to the original allocation entries.

### 3.7. Appeals and Re-measurement

A `PropertyOwner` (against their own parcel or bill) or a `StormwaterAdmin` files an appeal by supplying the `parcel_id`, an optional `bill_id`, the filing `account_id`, the `grounds`, and a free-text `narrative`. The `grounds` must be one of `MEASUREMENT_ERROR`, `LAND_USE_ERROR`, `EXEMPTION_DENIED`, or `CREDIT_DENIED`. When a `bill_id` is supplied, that bill must belong to the same parcel named as `parcel_id`; a bill that belongs to a different parcel is rejected with `ERR_APPEAL_BILL_MISMATCH`. A filed appeal begins `SUBMITTED`, and the filer's identifier is captured as `filed_by_user_id`. Appeals may be fetched individually or listed by `parcel_id`, `bill_id`, `account_id`, and `status`.

A `StormwaterAdmin` adjudicates. Moving a `SUBMITTED` appeal forward advances it from `SUBMITTED` to `UNDER_REVIEW`; attempting this step on an appeal that is not `SUBMITTED` is rejected with `ERR_APPEAL_NOT_REVIEWABLE`. From `UNDER_REVIEW`, an appeal grounded in `MEASUREMENT_ERROR` may be sent back for re-measurement, advancing it from `UNDER_REVIEW` to `NEEDS_REMEASURE` and flagging the parcel as awaiting an `APPEAL_REMEASURE` measurement; this step is rejected with `ERR_APPEAL_NOT_REVIEWABLE` when the appeal is not `UNDER_REVIEW` or when its `grounds` are anything other than `MEASUREMENT_ERROR`. The loop closes when an `Assessor` records a new measurement whose `source` is `APPEAL_REMEASURE` for the appealed parcel: that measurement returns the appeal from `NEEDS_REMEASURE` back to `UNDER_REVIEW`, so an appeal can cycle between `UNDER_REVIEW` and `NEEDS_REMEASURE` more than once before it is decided.

Deciding an appeal requires it to be `UNDER_REVIEW`; deciding one in any other state is rejected with `ERR_APPEAL_NOT_REVIEWABLE`. The administrator supplies an `outcome` and an optional `resolution_note`. When the outcome upholds the appeal, it moves from `UNDER_REVIEW` to `UPHELD`; if the appeal is linked to a bill, that bill is re-assessed and moves to `ADJUSTED`, provided it was `ISSUED`, `PARTIALLY_PAID`, or `DELINQUENT`. Re-assessment recomputes the bill's `base_fee_cents`, `credit_amount_cents`, `assessed_fee_cents`, and `net_fee_cents` from the parcel's current `billable_eru` and refreshes the bill's `eru_snapshot` to that current value; when the adjusted bill was `DELINQUENT`, its penalty is recomputed on the new assessed base. The charged account's `outstanding_balance_cents` and `delinquency_status` are then recomputed. When the outcome denies the appeal, it moves from `UNDER_REVIEW` to `DENIED`, the `resolution_note` is recorded, and no fee changes.

### 3.8. The Operations Cycle: Delinquency and Credit Expiry

Delinquency and credit expiry are not evaluated continuously; they are advanced by an operations checkpoint that a `BillingClerk` or `StormwaterAdmin` runs against the logical clock. Before running it, an operator advances the clock by supplying the target instant as `to_iso8601`; the clock endpoint returns the new `current_utc` but performs no delinquency work of its own. Running the cycle then evaluates every bill and every credit against that clock and reports how many bills it marked delinquent as `bills_marked_delinquent` and how many credits it expired as `credits_expired`.

A bill becomes delinquent when it is unpaid past its grace boundary. The grace period is 30 days: a bill is past the boundary when the logical clock has reached its `due_date` plus 30 days, and the boundary is inclusive — the clock reading exactly the due date plus 30 days is already past due. During the cycle, any bill whose status is `ISSUED` or `PARTIALLY_PAID`, whose `amount_paid_cents` is still less than its `net_fee_cents`, and which has crossed that boundary transitions to `DELINQUENT`. The delinquency penalty is 10 percent of the unpaid principal, where the unpaid principal is the bill's `assessed_fee_cents` minus its `amount_paid_cents`: the penalty is that product rounded to whole cents, written to `penalty_cents`, and the bill's `net_fee_cents` becomes the assessed fee plus the penalty. The penalty is charged once per bill — a later cycle over an already-delinquent bill does not add it again.

The same cycle expires stale credits. A credit's re-inspection is overdue when the logical clock has reached its `next_inspection_due` and no passing inspection has been recorded. Any `ACTIVE` credit that has reached its `next_inspection_due` transitions from `ACTIVE` to `EXPIRED`, its `credit_pct` is set to 0, and the parcel's `current_fee_cents` is recomputed with the credit removed and the parcel's `version` incremented. After marking bills and expiring credits, the cycle recomputes the `outstanding_balance_cents` and `delinquency_status` of every affected account. An account is `CURRENT` when none of its bills is past its `due_date`, `PAST_DUE` when some bill is past its `due_date` but still within the 30-day grace window, and `DELINQUENT` when some bill is past its `due_date` plus the 30-day grace window.

### 3.9. Voiding a Bill

A `BillingClerk` or a `StormwaterAdmin` may void a bill that was issued in error. Voiding is permitted only from `ISSUED`, `PARTIALLY_PAID`, or `DELINQUENT`, and only when the bill carries no `APPLIED` payment — any payment must be refunded first. A bill that is not in a voidable state, or that still has an applied payment, is rejected with `ERR_INVALID_STATE`. Voiding moves the bill to `VOID` and excludes it from the charged account's `outstanding_balance_cents`, after which the account's `delinquency_status` is recomputed.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; state transitions and other modifications return HTTP 200 with the updated resource; reads return HTTP 200. All request and response bodies use the envelope defined in Section 2.2. The request payload, computed response fields, and side effects of each endpoint are described in the Section 3 narratives; the table below lists only the HTTP surface and the roles authorized to call each operation.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/accounts` | Create a property account. | Assessor, StormwaterAdmin |
| GET | `/accounts/{id}` | Fetch an account with its computed balances. | Assessor, BillingClerk, StormwaterAdmin, PropertyOwner |
| POST | `/parcels` | Register a parcel under an account. | Assessor, StormwaterAdmin |
| GET | `/parcels/{id}` | Fetch a parcel with its computed ERU and fee. | Assessor, BillingClerk, StormwaterAdmin, PropertyOwner |
| GET | `/parcels` | List parcels, filterable by account or status. | Assessor, BillingClerk, StormwaterAdmin |
| GET | `/parcels/{id}/fee-quote` | Compute both fee variants for the parcel's current state without issuing a bill. | Assessor, BillingClerk, StormwaterAdmin, PropertyOwner |
| POST | `/impervious-measurements` | Record an authoritative measurement; supersedes the prior active one. | Assessor |
| GET | `/impervious-measurements/{id}` | Fetch a measurement. | Assessor, StormwaterAdmin, PropertyOwner |
| GET | `/impervious-measurements` | List measurements for a parcel. | Assessor, StormwaterAdmin |
| POST | `/exemptions` | File an exemption request for a parcel. | PropertyOwner, Assessor, StormwaterAdmin |
| GET | `/exemptions/{id}` | Fetch an exemption. | Assessor, StormwaterAdmin, PropertyOwner |
| GET | `/exemptions` | List exemptions for a parcel. | Assessor, StormwaterAdmin |
| POST | `/exemptions/{id}/decision` | Grant or deny a pending exemption. | Assessor, StormwaterAdmin |
| POST | `/bmp-credits` | Create a provisional BMP credit. | PropertyOwner, Assessor |
| GET | `/bmp-credits/{id}` | Fetch a BMP credit. | PropertyOwner, Assessor, CreditInspector, StormwaterAdmin |
| GET | `/bmp-credits` | List BMP credits for a parcel. | Assessor, CreditInspector, StormwaterAdmin |
| POST | `/credit-inspections` | Schedule a credit inspection. | CreditInspector |
| GET | `/credit-inspections/{id}` | Fetch a credit inspection. | CreditInspector, Assessor, StormwaterAdmin |
| GET | `/credit-inspections` | List inspections for a credit. | CreditInspector, StormwaterAdmin |
| POST | `/credit-inspections/{id}/complete` | Record inspection result; PASS re-scores, FAIL revokes. | CreditInspector |
| POST | `/bills` | Issue a stormwater bill snapshotting current ERU and credit. | BillingClerk |
| GET | `/bills/{id}` | Fetch a bill. | PropertyOwner, BillingClerk, StormwaterAdmin |
| GET | `/bills` | List bills, filterable by parcel or account. | BillingClerk, StormwaterAdmin |
| POST | `/bills/{id}/void` | Void a bill (must have no applied payment). | BillingClerk, StormwaterAdmin |
| POST | `/appeals` | File an appeal against a parcel or bill. | PropertyOwner, StormwaterAdmin |
| GET | `/appeals/{id}` | Fetch an appeal. | PropertyOwner, StormwaterAdmin, Assessor |
| GET | `/appeals` | List appeals, filterable by parcel, bill, or account. | StormwaterAdmin, Assessor |
| POST | `/appeals/{id}/review` | Move a submitted appeal into review. | StormwaterAdmin |
| POST | `/appeals/{id}/remeasure` | Send a measurement-error appeal back for re-measurement. | StormwaterAdmin |
| POST | `/appeals/{id}/decide` | Uphold or deny an appeal; UPHELD re-assesses the linked bill. | StormwaterAdmin |
| POST | `/payments` | Apply a payment to a bill; splits revenue into capital and operating funds. | PropertyOwner, BillingClerk |
| GET | `/payments/{id}` | Fetch a payment. | PropertyOwner, BillingClerk, StormwaterAdmin |
| GET | `/payments` | List payments by bill or account. | BillingClerk, StormwaterAdmin |
| POST | `/payments/{id}/refund` | Refund an applied payment (refunder must differ from creator). | BillingClerk |
| GET | `/fund-ledger/{id}` | Fetch a single fund-ledger entry. | BillingClerk, StormwaterAdmin |
| GET | `/fund-ledger` | List fund-ledger entries by source payment or fund. | BillingClerk, StormwaterAdmin |
| POST | `/billing/run-cycle` | Mark overdue bills delinquent with penalty and expire credits past inspection. | BillingClerk, StormwaterAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock. | Assessor, BillingClerk, CreditInspector, StormwaterAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_MISSING_FIELD | 400 |
| ERR_OUT_OF_RANGE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_BILL_NOT_PAYABLE | 409 |
| ERR_APPEAL_NOT_REVIEWABLE | 409 |
| ERR_INSPECTION_ALREADY_COMPLETED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_ACCOUNT_PARCEL_MISMATCH | 422 |
| ERR_APPEAL_BILL_MISMATCH | 422 |
| ERR_DUPLICATE_PARCEL | 409 |
| ERR_PARCEL_EXEMPT | 409 |
| ERR_INVALID_PERIOD | 422 |
| ERR_CREDIT_WINDOW_OVERLAP | 409 |
| ERR_BILL_PERIOD_OVERLAP | 409 |
| ERR_OVERPAYMENT | 422 |
