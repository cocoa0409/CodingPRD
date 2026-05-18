# Property Tax Assessment & Appeal API — Product Requirements Document

## 1. Introduction

Property tax administration is, at its heart, a long-running negotiation between a county and its property owners. A parcel is appraised, an assessed value is published, exemptions are claimed and stacked, an appeal may be filed before a statutory window closes, the Board of Equalization hears the case, a bill is issued, payments arrive, and — for owners in hardship — a deferral may roll the obligation forward at a daily-compounded interest rate. Each step is governed by precise statutory language and rigid segregation-of-duties rules, and a single mis-applied cap or mis-routed approval can trigger refunds that cascade three hops down the data model.

This API is the system of record for that entire flow. It owns the canonical assessed value of every property, the chronicled history of every appeal decision, the dollar-precise computation of every bill, and the audit trail of every payment, refund, and deferred-interest accrual. Two design forces dominate every decision below: first, *temporal precision* — the appeal window, the hearing interval, the bill due date, and the deferral term are all enforced at strict, monotonic boundaries because tax law demands a definite answer to "did this happen in time?". Second, *segregation of duties* — the county assessor who issues an assessment is structurally forbidden from also deciding the appeal against it, and the treasurer who issues a bill is the only role that can activate a deferral plan against it. The remainder of this document specifies those mechanics in detail.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is rooted under `/properties` for all property-scoped resources, with a small number of top-level fixture endpoints for `/owners`, `/hearing_officers`, and an administrative `/_clock/advance` capability described in §2.11.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which the user is acting. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. A request that carries valid headers but whose role is not authorized for the requested operation is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled and capitalized exactly as follows: `Assessor`, `Treasurer`, `HearingOfficer`, and `Owner`.

The relationship between `X-User-ID` and the persisted entities differs by role:

- When `X-User-Role` is `Assessor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as the user who issued an Assessment for later segregation-of-duties checks) but does not compare it against any entity's `id`.
- When `X-User-Role` is `Treasurer`, `X-User-ID` is likewise opaque and not entity-backed; the server may record it on operations the treasurer performs, but no ownership check looks it up against a persisted entity.
- When `X-User-Role` is `HearingOfficer`, `X-User-ID` is the `id` of the acting `HearingOfficer` entity; ownership and identity checks compare `Hearing.officer_id` against `X-User-ID` directly.
- When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` entity; for every owner-scoped write — filing an appeal, submitting an exemption application, making a payment, requesting or cancelling a deferral, withdrawing an appeal — the server compares `Property.owner_id` against `X-User-ID` and rejects mismatches with `ERR_OWNERSHIP_MISMATCH`.

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

List-returning endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has no upper bound beyond the size of the underlying result set. Unless an endpoint description in §3 says otherwise, list results are returned sorted by `created_at` in ascending order. The pagination envelope in `meta` carries `limit`, `offset`, `total_count`, and `has_more` for every list response.

### 2.4. Common Resource Properties

Almost every resource the API exposes carries the same four system-managed fields:

- `id` — a server-minted UUID. No type prefix is attached; the value is a bare UUID.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, captured when the resource is first persisted.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer starting at 1 and incremented by exactly 1 on every mutation. Cascaded mutations described in §3 — for example, when an Assessment finalization recomputes a `TaxBill`, or when a hold-style transition propagates back to a parent — independently bump `updated_at` and `version` on every entity they touch.

The single exception is `Payment`. Payments are immutable once written: a `Payment` carries `id` and `created_at` and, when its status changes from `APPLIED` to `REFUNDED` as part of an appeal reconciliation, the change is modeled by splitting the row (see §3.5) rather than mutating in place. `Payment` therefore exposes neither `updated_at` nor `version`.

### 2.5. Nested Resource Retrieval and Path Validation

Most URL paths in this API are nested several levels deep — `/properties/{property_id}/tax_bills/{tax_bill_id}/deferral_plans/{deferral_plan_id}` is representative. When such a path is processed, the server validates path identifiers strictly left-to-right and stops at the first one that does not resolve. The error returned is always `ERR_NOT_FOUND` and refers to the first unresolved segment, never to a deeper one. Likewise, foreign-key identifiers carried in the request body (such as `assessment_id`, `officer_id`, or `new_owner_id`) must resolve to existing rows; the first missing reference wins. Validation order across the entire stack — auth, RBAC, path/FK existence, ownership, state, then domain-specific checks — is described per-endpoint in §3 and codified in the priority list backing each error.

### 2.6. Monetary Values and Rounding

All money in the system — `market_value`, `market_value_at_roll`, `capped_value`, `prior_capped_value`, `approved_amount`, `taxable_value`, `total_exemption_amount`, `base_tax_amount`, `total_payments_applied`, `amount_due`, `principal_deferred`, `accrued_interest`, `claimed_value`, `decided_value`, `Payment.amount` — is stored and returned as a JSON number with at most two decimal places. The rounding rule is **round half up** to two decimal places; intermediate steps in every multi-step calculation are rounded at the boundaries that §3.4 and §3.5 pin explicitly. Rates such as `mill_rate` and `annual_interest_rate` are exempt from the two-decimal rule and preserve the precision at which they were captured.

### 2.7. State Enumerations

For unambiguous reference, the canonical state strings the API uses are listed once here; their lifecycle semantics live in §3.

- `Assessment.status` ∈ { `DRAFT`, `ISSUED`, `UNDER_APPEAL`, `FINALIZED` }.
- `ExemptionApplication.status` ∈ { `SUBMITTED`, `APPROVED`, `DENIED`, `REVOKED` } with `revoked_reason` ∈ { `OWNERSHIP_CHANGE`, `INELIGIBLE`, `WITHDRAWN` } when revoked.
- `Appeal.status` ∈ { `FILED`, `SCHEDULED`, `HEARD`, `DECIDED`, `WITHDRAWN` } with `decision_outcome` ∈ { `UPHELD`, `REDUCED`, `INCREASED` } once decided. `filed_grounds` is one of `OVER_MARKET`, `EXEMPTION_DENIED`, `CAP_MISAPPLIED`, or `CLERICAL_ERROR`.
- `Hearing.status` ∈ { `SCHEDULED`, `CONDUCTED`, `RESCHEDULED`, `CANCELLED` }; `hearing_room` is one of `ROOM_A`, `ROOM_B`, `ROOM_C`.
- `TaxBill.status` ∈ { `PENDING`, `ISSUED`, `PARTIALLY_PAID`, `PAID`, `IN_DEFERRAL`, `DELINQUENT` }.
- `DeferralPlan.status` ∈ { `REQUESTED`, `ACTIVE`, `COMPLETED`, `DEFAULTED` }.
- `Payment.status` ∈ { `APPLIED`, `REFUNDED` }; `refund_reason` is one of `APPEAL_REDUCED` or `OVERPAYMENT` when set, and remains null otherwise.
- `ExemptionApplication.exemption_type` ∈ { `HOMESTEAD`, `SENIOR`, `VETERAN`, `DISABILITY` }.

### 2.8. Segregation of Duties

Tax administration imposes a hard separation between the official who values a property, the official who collects on it, the panel that hears disputes, and the property owner themselves. Three rules follow:

- An `Assessor` may create, issue, and amend Assessments and may approve, deny, or revoke `ExemptionApplication`s; an `Assessor` may not schedule, conduct, or decide an `Appeal`.
- A `Treasurer` may create and issue `TaxBill`s, schedule hearings, and activate `DeferralPlan`s; a `Treasurer` may not approve exemptions or render appeal decisions.
- For any given Appeal, the `HearingOfficer` who is recorded as the presiding officer (via `Hearing.officer_id`) must not be the same user who issued the underlying Assessment. The server enforces this by comparing the officer to the recorded issuer at schedule time and rejecting violations with `ERR_BOE_OFFICER_CONFLICT`. Once scheduling has captured an officer, the user who later conducts and decides the hearing must equal that captured `officer_id`; substitution at the bench is rejected with `ERR_OFFICER_MISMATCH`.

### 2.9. Validation Ordering

When several validation categories could each independently reject a single request, the server evaluates them in a fixed priority order so that the returned `error_id` is deterministic. Authentication header presence is checked first (`ERR_UNAUTHENTICATED`), then role authorization for the requested operation (`ERR_FORBIDDEN`), then path-and-FK existence left-to-right (`ERR_NOT_FOUND`), then ownership of the target property for owner-scoped writes (`ERR_OWNERSHIP_MISMATCH`), then the target resource's state-machine eligibility (`ERR_INVALID_STATE`), then cross-entity preconditions such as the `Assessment` being `FINALIZED` before a bill can issue (`ERR_ASSESSMENT_NOT_FINALIZED`), then temporal gates such as the appeal window or hearing-interval validity, then business constraints such as room overlap, officer-buffer, exemption uniqueness, exemption eligibility, payment-amount sanity, bill duplication, and the segregation-of-duties checks, then the appeal decision-value consistency rule, and finally the optimistic-concurrency `version` check. Every individual rule's threshold and the error it raises is described in the relevant §3 subsection, but the ordering itself is fixed system-wide: a request that fails two checks will always surface the higher-priority one.

### 2.10. Optimistic Concurrency Control

All transition endpoints that accept a request body permit an optional `version` field. When `version` is supplied, the server compares it against the target resource's current `version`; a mismatch fails the request with `ERR_VERSION_MISMATCH`. When `version` is omitted from the request body, the OCC check is skipped and the request proceeds against whatever version is current. Successful mutations always increment `version` by exactly 1 and refresh `updated_at`, regardless of whether the client supplied a `version`. Where a single endpoint causes cascading mutations to sibling or child resources (see §3.5 on appeal reconciliation), each independently affected resource has its own `version` bumped.

### 2.11. Logical Clock and Time-Gated Transitions

Several lifecycle transitions in this domain depend on wall-clock time: appeal windows close, tax bills become delinquent, and deferral plans default once their term expires. To make this testable, the API exposes a single administrative capability that advances a logical server clock to a supplied `target_timestamp`. Any authenticated user — `Assessor`, `Treasurer`, `HearingOfficer`, or `Owner` — may invoke it. On invocation, the server scans for state transitions whose temporal preconditions have become satisfied and applies them atomically: Assessments whose appeal window has closed without any filed Appeal auto-finalize, `TaxBill`s past their `due_date` without an `ACTIVE` deferral auto-flip to `DELINQUENT`, `DeferralPlan`s whose elapsed term has exceeded `DEFERRAL_MAX_TERM_DAYS` (365 days) auto-default and cascade the bill to `DELINQUENT`, and `accrued_interest` values on `ACTIVE` deferrals are refreshed so subsequent reads return current numbers. Time advances monotonically; the clock cannot be rewound.

### 2.12. Concurrency and Serialization Guarantees

The system serializes the small set of races that the domain admits, and the loser of each race receives a deterministic `error_id`:

- Two `Owner`s simultaneously filing an `Appeal` against the same `ISSUED` `Assessment` whose appeal window has only seconds remaining: both filings may succeed in creating `Appeal` rows, because multiple appeals are permitted, but only the first writer that flips the `Assessment.status` from `ISSUED` to `UNDER_APPEAL` wins that transition. The losing writer observes `UNDER_APPEAL` and either appends silently or, when the contention is on the `Assessment.version` carried in the request body, is rejected with `ERR_VERSION_MISMATCH`.
- An `Owner` withdrawing the last open `Appeal` (which would revert the `Assessment` from `UNDER_APPEAL` back to `ISSUED`) while a `Treasurer` simultaneously schedules a new `Appeal` (which requires the `Assessment` to remain in `UNDER_APPEAL`): exactly one wins, the loser receives `ERR_INVALID_STATE`, and the resolution is first-writer-wins on `Assessment.status`.
- Two simultaneous scheduling requests targeting the same `hearing_room` with overlapping intervals: at most one Hearing in `SCHEDULED` status can exist per room with overlapping intervals, and the second is rejected with `ERR_ROOM_DOUBLE_BOOKED`.
- Two `Payment` requests against the same `TaxBill` that each individually equal the current `amount_due`: exactly one is `APPLIED` and fully pays the bill; the other is rejected with `ERR_OVERPAYMENT`. Serialization is first-writer-wins on `TaxBill.version`.
- An `Owner` activating a `DeferralPlan` while a `Payment` that would fully pay the bill is being applied: exactly one wins. If the payment wins, the bill becomes `PAID` and the deferral activation is rejected with `ERR_INVALID_STATE`; if the deferral wins, the payment is rejected with `ERR_OVERPAYMENT` because it would be applied against a bill that has just transitioned to `IN_DEFERRAL`.
- Two `Assessor`s attempting to approve different `ExemptionApplication`s of the same `exemption_type` for the same `(property_id, effective_roll_year)`: at most one APPROVED row may exist for that triple, and the loser is rejected with `ERR_EXEMPTION_DUPLICATE`.

## 3. Business Logic & Workflows

This section walks through the lifecycle of a property's tax year, from owner and parcel registration through deferral closure, and along the way introduces the input parameters, derived fields, and side effects each operation produces. Endpoints are referred to by their effect on state and by the role acting on them; the HTTP surface itself is tabulated in §4.

### 3.1. Owners, Officers, and Property Registration

The system bootstraps with three small registration flows. An `Assessor` or a `Treasurer` may register an `Owner` by supplying `full_name` and `date_of_birth`; two additional inputs, `veteran_status` (a boolean, default `false`) and `disability_rating` (an integer percentage from 0 to 100, default `0`), are optional at creation time and feed eligibility decisions later. A `Treasurer` may register a `HearingOfficer` with `full_name` and an optional `active` flag (default `true`). When `active` is `false`, the officer is ineligible to be assigned to a new hearing.

Property registration is the responsibility of the `Assessor`, who supplies `owner_id`, `parcel_number`, and `market_value`. The `parcel_number` is the tax-jurisdiction-unique key for the parcel and is immutable after creation. On registration, the server initializes `capped_value` equal to the supplied `market_value` (there is no prior roll basis to grow against) and records `ownership_change_date` as the current server time; `current_assessment_year` begins unset and is filled once an Assessment for the property is issued.

Ownership transfers are also performed by the `Assessor`, who supplies a new `new_owner_id` and the property's current `version`. On transfer, `Property.owner_id` is updated, `ownership_change_date` is refreshed to the current server time, and a cascade fires: every `APPROVED` `ExemptionApplication` for the property's current roll year is auto-revoked with `revoked_reason` set to `OWNERSHIP_CHANGE`, the exemption stack is recomputed from scratch, and any non-finalized `TaxBill` for that roll year is recomputed under the new stack.

### 3.2. The Assessment Cycle

An Assessment is the formal valuation of a property for a specific tax `roll_year`. Each Assessment is unique per `(property_id, roll_year)`; at most one Assessment per property may exist in any of `ISSUED`, `UNDER_APPEAL`, or `FINALIZED` status for the same roll year, and any attempt to issue a second triggers `ERR_DUPLICATE_ROLL_YEAR`. An `Assessor` first creates an Assessment in `DRAFT` by supplying `roll_year` and `market_value_at_roll`. The server resolves `prior_assessment_id` automatically to the most recent Assessment for the same property whose `roll_year` is strictly less than the new one (null if this is the property's first roll).

Issuing the Assessment (transitioning it from `DRAFT` to `ISSUED`) is the moment the capped value is computed. The `Assessor` calls the issue endpoint with an optional `version`; the server computes `capped_value` via the rule described below, sets `cap_reset_applied` accordingly, records `issued_at` as the current time, computes `appeal_window_closes_at` as `issued_at` plus 30 days (the system constant `APPEAL_WINDOW_DAYS`), and writes `Property.current_assessment_year` to the Assessment's `roll_year`.

**The capped-value computation** is evaluated in a strict two-step order, and the order matters: reset detection runs first; growth-cap math runs only if no reset condition was found.

Step 1 — reset detection. If `prior_capped_value` equals zero (which is true on the property's first roll), or if `ownership_change_date` is not null and falls on or after midnight UTC on January 1 of the Assessment's `roll_year` and on or before 23:59:59 UTC on December 31 of that same year, then `capped_value` is set equal to `market_value_at_roll` and `cap_reset_applied` is `True`. The growth cap is bypassed in this branch.

Step 2 — growth cap. If neither reset condition holds, the server first computes a ceiling equal to `prior_capped_value` multiplied by 1.02 (one plus the system growth-cap constant `GROWTH_CAP`, which is 2 percent — the Prop-13-style annual growth cap), then rounded half up to two decimal places. The `capped_value` is then the smaller of `market_value_at_roll` and that ceiling. `cap_reset_applied` is `False` in this branch.

The Assessment transitions onward from `ISSUED` along two mutually exclusive paths. If an `Owner` files an `Appeal` against the Assessment before the appeal window closes, the Assessment automatically transitions `ISSUED → UNDER_APPEAL`. If, instead, the logical clock advances past `appeal_window_closes_at` without any `Appeal` having been filed, the Assessment automatically transitions `ISSUED → FINALIZED` (recording `finalized_at`), and a `TaxBill` is auto-created in `PENDING` status with `taxable_value` and `base_tax_amount` already computed.

Once the Assessment is `UNDER_APPEAL`, two onward transitions are possible. If every open `Appeal` against the Assessment is withdrawn, the Assessment reverts `UNDER_APPEAL → ISSUED` and is again appeal-eligible until `appeal_window_closes_at` (no extension of that deadline). If, instead, the last remaining open Appeal is `DECIDED`, the Assessment transitions `UNDER_APPEAL → FINALIZED`; `finalized_at` is recorded, `capped_value` is updated to the `decided_value` from the deciding Appeal when its `decision_outcome` is `REDUCED` or `INCREASED`, and the cascade described in §3.5 runs against any existing `TaxBill` for the same `(property_id, roll_year)`.

### 3.3. Exemption Applications and the Exemption Stack

An `Owner` files an `ExemptionApplication` by supplying `exemption_type` and `effective_roll_year`; the server captures `owner_id` from `X-User-ID` and `property_id` from the path. The application begins in `SUBMITTED` status. An `Assessor` may then approve, deny, or — for an already-approved application — revoke it (the revoke call requires `revoked_reason` to be supplied).

Approval (`SUBMITTED → APPROVED`) enforces several preconditions. The Owner whose id is on the application must equal `Property.owner_id` at the moment of approval, or the request is rejected with `ERR_OWNERSHIP_MISMATCH`. At most one APPROVED application of the same `exemption_type` may exist for the same `(property_id, effective_roll_year)`; a second is rejected with `ERR_EXEMPTION_DUPLICATE`. And the Owner must satisfy the type-specific eligibility test, otherwise the response is `ERR_EXEMPTION_INELIGIBLE`:

- `HOMESTEAD` requires that the applying `Owner` is the current `Property.owner_id`.
- `SENIOR` requires that the `Owner`'s age, computed from `date_of_birth`, is at least 65 (the system constant `SENIOR_AGE`) measured on January 1 of `effective_roll_year`.
- `VETERAN` requires `Owner.veteran_status` to be `true`.
- `DISABILITY` requires `Owner.disability_rating` to be at least 50 percent (the system constant `DISABILITY_MIN_PCT`).

Approval sets `status` to `APPROVED`, records `approved_at`, and computes `approved_amount` via the exemption-stack rule below. It then cascades: any `TaxBill` for `(property_id, effective_roll_year)` in `PENDING`, `ISSUED`, or `PARTIALLY_PAID` is recomputed.

Denial (`SUBMITTED → DENIED`) has no preconditions other than the state being `SUBMITTED` and simply records the status change.

Revocation (`APPROVED → REVOKED`) requires `revoked_reason` to be one of `OWNERSHIP_CHANGE`, `INELIGIBLE`, or `WITHDRAWN`. On revocation, the `approved_amount` no longer counts toward the exemption stack, and any `TaxBill` for the affected roll year is recomputed; if the recompute makes the bill underpaid relative to total payments already applied, its status becomes `PARTIALLY_PAID` and `amount_due` grows accordingly.

**The exemption stack** is computed per `(property_id, roll_year)` in a pinned priority order — `HOMESTEAD`, then `SENIOR`, then `VETERAN`, then `DISABILITY`. Only `APPROVED` applications participate; `SUBMITTED` and `REVOKED` are excluded. The base value at the start of the stack is the Assessment's `capped_value`; `total_exemption_amount` starts at zero. For each `exemption_type` in that order, if no `APPROVED` application of that type exists for the roll year, the layer is skipped. Otherwise the layer's dollar amount is computed as follows:

- `HOMESTEAD`: the smaller of 20 percent of the residual base (the system constant `HOMESTEAD_PCT` is 0.20) and the absolute dollar cap of 75,000 (the system constant `HOMESTEAD_CAP_DOLLARS`), rounded half up to two decimal places.
- `SENIOR`: a flat 25,000 (the system constant `SENIOR_FLAT`).
- `VETERAN`: a flat 15,000 (the system constant `VETERAN_FLAT`).
- `DISABILITY`: if `Owner.disability_rating` is at least 70, the full 30,000 (the system constant `DISABILITY_FULL`); otherwise half of `DISABILITY_FULL`, i.e. 15,000, rounded half up to two decimal places.

Each computed layer amount is then floored at the current residual base (so a layer can never reduce the residual below zero); the floored amount is stored on its `ExemptionApplication` as `approved_amount`, subtracted from the residual base, and added to the running `total_exemption_amount`. Rounding is applied per-layer, not once at the end.

### 3.4. Tax Bill Issuance, Payment, and the Tax-Bill Computation

A `TaxBill` is created by the `Treasurer` once the underlying Assessment is `FINALIZED`. The treasurer supplies `roll_year` and may optionally supply `mill_rate`; if `mill_rate` is omitted, the system constant `DEFAULT_MILL_RATE` (12.5 per $1000 of taxable value) is captured on the bill. At most one `TaxBill` may exist per `(property_id, roll_year)`; duplicates are rejected with `ERR_DUPLICATE_BILL`. The bill is created in `PENDING` and immediately has its `taxable_value`, `total_exemption_amount`, and `base_tax_amount` computed.

**The tax-bill computation** runs every time the bill is created, every time an `ExemptionApplication` for its roll year changes status, and every time the underlying Assessment is `FINALIZED` with a changed `capped_value`. The pinned evaluation order is:

1. Start from `capped_value`, already rounded to two decimal places on the Assessment.
2. Pull `total_exemption_amount` from the exemption-stack rule in §3.3 (which itself applies per-layer rounding).
3. Compute `taxable_value` as `capped_value` minus `total_exemption_amount`, rounded half up to two decimal places, then floored at zero — so the taxable value never goes negative even if the exemption stack exceeds the capped value.
4. Compute `base_tax_amount` as `taxable_value` multiplied by `mill_rate`, then divided by 1,000, then rounded half up to two decimal places. The `mill_rate` is pinned at the moment the bill is created and is not modified by later jurisdictional rate changes; this is version-pinning of the rate at issuance.
5. Compute `total_payments_applied` as the sum of `Payment.amount` for every `Payment` on this bill whose status is `APPLIED`.
6. Compute `amount_due` as `base_tax_amount` minus `total_payments_applied` plus any deferral-accrued interest (zero unless an `ACTIVE` `DeferralPlan` exists on this bill), rounded half up to two decimal places, then floored at zero.

Issuance of a `PENDING` bill (`PENDING → ISSUED`) is performed by the `Treasurer` with an optional `version`. Two cross-entity preconditions guard the transition: the linked Assessment must be `FINALIZED`, otherwise `ERR_ASSESSMENT_NOT_FINALIZED`; and no `ExemptionApplication` for `(property_id, roll_year)` may still be in `SUBMITTED` status, otherwise `ERR_EXEMPTIONS_PENDING` — the system refuses to issue a bill while exemptions are still pending decision. On successful issuance, `issued_at` is set to now, `due_date` is set to `issued_at` plus the system constant `DUE_WINDOW_DAYS` (30 days), and `amount_due` is locked to the current `base_tax_amount`.

An `Owner` then applies payments. Each payment carries only an `amount`, which must be strictly greater than zero and strictly less than or equal to the current `amount_due`; zero, negative, or overpaying amounts are all rejected with `ERR_OVERPAYMENT`. On a successful payment, a `Payment` row is created in `APPLIED` status with `applied_at` set to now (Payment rows are immutable; `applied_at` doubles as their `created_at`), `total_payments_applied` increases by the payment amount, and `amount_due` is recomputed. If the new payment exactly equals the previous `amount_due`, the bill transitions to `PAID`; if it is strictly less, the bill transitions to `PARTIALLY_PAID` (or stays `PARTIALLY_PAID` if it was already there). A payment that exactly clears a `PARTIALLY_PAID` bill flips it to `PAID`.

The payments list endpoint accepts `limit`, `offset`, and an optional `status` query filter constraining the result to `APPLIED` or `REFUNDED` rows.

If the logical clock advances past `due_date` and the bill is still in `ISSUED` or `PARTIALLY_PAID` with no `ACTIVE` `DeferralPlan`, the bill auto-transitions to `DELINQUENT`. If a `DeferralPlan` is `ACTIVE` on the bill, the delinquency check defers to the deferral logic in §3.6 instead.

### 3.5. Appeals, Hearings, and Decision Reconciliation

Filing an `Appeal` requires an `Owner` to supply `assessment_id`, `filed_grounds` (one of `OVER_MARKET`, `EXEMPTION_DENIED`, `CAP_MISAPPLIED`, or `CLERICAL_ERROR`), and `claimed_value`. The server captures `owner_id` from `X-User-ID` and `property_id` from the path. The strict precondition is that the current logical time is strictly less than the Assessment's `appeal_window_closes_at`; at the exact equality boundary the window is treated as closed and the request is rejected with `ERR_APPEAL_WINDOW_CLOSED`. The Assessment itself must be in `ISSUED` (or already in `UNDER_APPEAL` — additional Appeals on the same Assessment are permitted while the window remains open).

On a successful filing, the Appeal is created in `FILED` status, `assessment_version` is captured from the Assessment's current `version` (version-pinning so the appeal references the precise snapshot it was filed against), and the Assessment transitions `ISSUED → UNDER_APPEAL` (idempotently — if it is already there, no transition occurs but the appeal still attaches).

Scheduling (`FILED → SCHEDULED`) is performed by the `Treasurer`, who supplies `scheduled_start`, `scheduled_end`, `hearing_room`, `officer_id`, and an optional `version`. The server creates a `Hearing` row tied 1:1 to the live SCHEDULED hearing for this Appeal. Several scheduling constraints must hold:

- `scheduled_end` must be strictly greater than `scheduled_start`; otherwise `ERR_HEARING_INTERVAL_INVALID`.
- The interval `(scheduled_end − scheduled_start)` must not exceed the system constant `HEARING_MAX_DURATION_MIN` (120 minutes); otherwise `ERR_HEARING_INTERVAL_INVALID`.
- `officer_id` must reference an `active` `HearingOfficer`.
- `officer_id` must not be the same user who issued the underlying Assessment; otherwise `ERR_BOE_OFFICER_CONFLICT` (segregation of duties, see §2.8).
- No other `Hearing` in `SCHEDULED` status may already occupy the same `hearing_room` with a `[scheduled_start, scheduled_end)` interval that overlaps the requested one; intervals are half-open so two hearings that are instant-adjacent (one ends exactly when the next begins) are permitted. Conflicting overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED`.
- No other `Hearing` in `SCHEDULED` for the same `officer_id` may sit within the system constant `OFFICER_BUFFER_MIN` minutes (15 minutes) of the requested interval — measured edge-to-edge, so even non-overlapping but tightly packed bookings are rejected with `ERR_OFFICER_BUFFER_VIOLATED`.

Successful scheduling sets `Appeal.status` and `Hearing.status` to `SCHEDULED`; the `Hearing` row carries `appeal_id` (the live SCHEDULED hearing is 1:1 with its appeal) and a denormalized `property_id` for routing. Conducting (`SCHEDULED → HEARD`) is performed by the `HearingOfficer` whose id equals the captured `Hearing.officer_id`; substitution at the bench is rejected with `ERR_OFFICER_MISMATCH`. The current time must be at or after `Hearing.scheduled_start` and strictly less than `Hearing.scheduled_end` plus a system grace period of 30 minutes (the system constant `GRACE_MIN`). On success, `Appeal.status` becomes `HEARD` and `Hearing.status` becomes `CONDUCTED`.

Deciding (`HEARD → DECIDED`) is also performed by the same `HearingOfficer` and requires `decision_outcome` (one of `UPHELD`, `REDUCED`, or `INCREASED`), `decided_value`, and an optional `version`. The decided value must satisfy the outcome relative to the Assessment's `capped_value` as captured at the time the Appeal was filed: `REDUCED` requires `decided_value` strictly less than that captured `capped_value`; `INCREASED` requires it strictly greater; `UPHELD` requires it exactly equal. A mismatched decision is rejected with `ERR_DECISION_VALUE_INCONSISTENT`. On success, `Appeal.status` becomes `DECIDED`, `decision_outcome` and `decided_value` are stored, and a three-hop cascade fires:

1. The Assessment's `capped_value` is updated to `decided_value` if the outcome is `REDUCED` or `INCREASED` (unchanged if `UPHELD`); the Assessment's `version` and `updated_at` are bumped.
2. The `TaxBill` for `(property_id, roll_year)` — if one exists — is recomputed via the tax-bill computation in §3.4, against the new `capped_value`.
3. If, after recomputation, `total_payments_applied` exceeds the new `base_tax_amount`, the bill has excess paid that must be refunded. The reconciliation runs in one of two variants:
   - **Refund-first (REDUCED outcome).** The excess is computed as the previous `total_payments_applied` minus the new `base_tax_amount`. The oldest `APPLIED` Payments — ordered ascending by `applied_at` with `id` ascending as the tie-break — are flipped to `REFUNDED` with `refund_reason` set to `APPEAL_REDUCED`, until the cumulative refunded amount is at least the excess. The last refund may be partial, in which case the affected Payment row is split into two immutable rows: an `APPLIED` remainder and a `REFUNDED` chunk. After refunds, `amount_due` is recomputed as the new `base_tax_amount` minus the new sum of remaining `APPLIED` Payments, floored at zero.
   - **Credit-carry (INCREASED outcome).** No Payments are refunded; `amount_due` is simply the new `base_tax_amount` minus the existing `total_payments_applied`, which may be larger than it was before. If the result, combined with the clock having advanced past `due_date`, would make the bill delinquent, that cascade fires accordingly.

   The choice between variants is pinned by outcome: `REDUCED` always uses refund-first; `INCREASED` always uses credit-carry; `UPHELD` triggers no monetary change but still records the decision.

4. Finally, if no `Appeal` against the Assessment remains in `FILED`, `SCHEDULED`, or `HEARD` after this decision, the Assessment auto-transitions `UNDER_APPEAL → FINALIZED`.

Withdrawing an `Appeal` (`FILED → WITHDRAWN`, `SCHEDULED → WITHDRAWN`, or `HEARD → WITHDRAWN`) is always permitted by the `Owner` who filed it. The Appeal's `status` becomes `WITHDRAWN`; if a `Hearing` was already `SCHEDULED`, its status flips to `CANCELLED`. If no remaining Appeal on the Assessment is in `FILED`, `SCHEDULED`, or `HEARD`, the Assessment reverts `UNDER_APPEAL → ISSUED` and is once again appeal-eligible — but only until the original `appeal_window_closes_at`; the window is never extended by withdrawal.

### 3.6. Deferral Plans and Interest Accrual

A `DeferralPlan` is the system's hardship-relief mechanism: an `Owner` who qualifies may request that a `TaxBill`'s `amount_due` be rolled forward, with daily-compounded interest, instead of paid immediately. The request flow has three actors and three states beyond `REQUESTED`.

An `Owner` requests a deferral by calling the deferral-request endpoint (no body fields are required beyond the path); the `DeferralPlan` is created in `REQUESTED` status, carrying `tax_bill_id` (the bill it defers, 1:1 with the bill's active deferral) and a denormalized `property_id`. The `Owner` may cancel a request that has not yet been activated; this transitions the plan `REQUESTED → DEFAULTED` and is the model's way of recording a cancellation — the bill itself is unaffected and remains in whatever status it had before.

A `Treasurer` activates the plan (`REQUESTED → ACTIVE`) by supplying an optional `version`. Activation is gated by an eligibility check: the property's `Owner` must satisfy at least one hardship indicator — either `Owner.disability_rating` at least 50 percent (the system constant `DEFERRAL_DISABILITY_MIN_PCT`) or the `Owner`'s age computed from `date_of_birth` is at least the system constant `SENIOR_AGE` (65 years). Failure raises `ERR_DEFERRAL_NOT_ELIGIBLE`. The linked `TaxBill` must be in `ISSUED` or `PARTIALLY_PAID` at activation; other states are rejected with `ERR_INVALID_STATE` and, where appropriate, `ERR_ASSESSMENT_NOT_FINALIZED`. On successful activation, `status` becomes `ACTIVE`, `started_at` is set to now, `principal_deferred` is captured equal to the bill's `amount_due` at this exact moment, `annual_interest_rate` is captured from the system constant `DEFERRAL_INTEREST_RATE` (5 percent annually), and the bill cascades to `IN_DEFERRAL`.

**Interest accrual** is computed in a pinned chronological form whenever the plan is read and whenever the logical clock advances. The number of elapsed days is the floor of the difference between the current time and `started_at`, expressed in whole days. The daily rate is `annual_interest_rate` divided by 365.0. The accrued interest is `principal_deferred` multiplied by the quantity `(1 + daily_rate) raised to the power days_elapsed, then minus 1`, with the final result rounded half up to two decimal places exactly once — never per-day. When `days_elapsed` is zero (a same-day deferral), `accrued_interest` is exactly 0.00. Once a plan reaches a terminal state (`COMPLETED` or `DEFAULTED`), `accrued_interest` is frozen at the value computed at `closed_at`.

Two paths close an `ACTIVE` plan. The `Owner` pays off the deferred balance in a single payment whose `amount` equals `principal_deferred` plus `accrued_interest` at that moment; the bill transitions `IN_DEFERRAL → PAID`, the plan transitions `ACTIVE → COMPLETED`, and `closed_at` is recorded. Alternatively, if the logical clock advances past `started_at` plus the system constant `DEFERRAL_MAX_TERM_DAYS` (365 days), the plan auto-transitions `ACTIVE → DEFAULTED`, `closed_at` is recorded, and the bill cascades from `IN_DEFERRAL` to `DELINQUENT`.

## 4. Endpoint Definitions

The status code convention across the API is straightforward: endpoints that create a brand-new resource return 201; endpoints that read, modify, or transition an existing resource return 200; error responses use the HTTP status codes listed in §5 against each `error_id`. All endpoints require the `X-User-ID` and `X-User-Role` headers described in §2.1; the table below names the roles authorized to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /owners | Register an `Owner`. | Assessor, Treasurer |
| GET | /owners/{owner_id} | Fetch an `Owner`. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /hearing_officers | Register a Board of Equalization `HearingOfficer`. | Treasurer |
| GET | /hearing_officers/{officer_id} | Fetch a `HearingOfficer`. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /properties | Register a `Property`. | Assessor |
| GET | /properties/{property_id} | Fetch a `Property` with derived `capped_value`. | Assessor, Treasurer, HearingOfficer, Owner |
| PATCH | /properties/{property_id}/owner | Transfer ownership; cascade-revokes APPROVED exemptions for the current roll year. | Assessor |
| POST | /properties/{property_id}/assessments | Create a DRAFT `Assessment`. | Assessor |
| GET | /properties/{property_id}/assessments/{assessment_id} | Fetch an `Assessment`. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /properties/{property_id}/assessments/{assessment_id}/issue | Issue an `Assessment` (DRAFT → ISSUED). | Assessor |
| POST | /properties/{property_id}/exemption_applications | Submit an `ExemptionApplication`. | Owner |
| POST | /properties/{property_id}/exemption_applications/{exemption_application_id}/approve | Approve (SUBMITTED → APPROVED). | Assessor |
| POST | /properties/{property_id}/exemption_applications/{exemption_application_id}/deny | Deny (SUBMITTED → DENIED). | Assessor |
| POST | /properties/{property_id}/exemption_applications/{exemption_application_id}/revoke | Revoke (APPROVED → REVOKED) with `revoked_reason`. | Assessor |
| POST | /properties/{property_id}/appeals | File an `Appeal` against an ISSUED `Assessment`. | Owner |
| GET | /properties/{property_id}/appeals/{appeal_id} | Fetch an `Appeal`. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /properties/{property_id}/appeals/{appeal_id}/schedule | Schedule a `Hearing` (FILED → SCHEDULED). | Treasurer |
| POST | /properties/{property_id}/appeals/{appeal_id}/conduct | Conduct the hearing (SCHEDULED → HEARD). | HearingOfficer |
| POST | /properties/{property_id}/appeals/{appeal_id}/decide | Render decision (HEARD → DECIDED); fires the reconciliation cascade. | HearingOfficer |
| POST | /properties/{property_id}/appeals/{appeal_id}/withdraw | Owner withdraws an `Appeal`. | Owner |
| GET | /properties/{property_id}/appeals/{appeal_id}/hearing | Fetch the `Hearing` for an `Appeal`. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /properties/{property_id}/tax_bills | Create a `TaxBill` (PENDING) for a FINALIZED Assessment year. | Treasurer |
| GET | /properties/{property_id}/tax_bills/{tax_bill_id} | Fetch a `TaxBill`. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /properties/{property_id}/tax_bills/{tax_bill_id}/issue | Issue a PENDING bill (PENDING → ISSUED). | Treasurer |
| POST | /properties/{property_id}/tax_bills/{tax_bill_id}/payments | Apply a `Payment` to a `TaxBill`. | Owner |
| GET | /properties/{property_id}/tax_bills/{tax_bill_id}/payments | List `Payment`s with `limit`, `offset`, and optional `status` filter. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /properties/{property_id}/tax_bills/{tax_bill_id}/deferral_plans | Request a `DeferralPlan` (REQUESTED). | Owner |
| POST | /properties/{property_id}/tax_bills/{tax_bill_id}/deferral_plans/{deferral_plan_id}/activate | Activate (REQUESTED → ACTIVE); bill cascades to IN_DEFERRAL. | Treasurer |
| POST | /properties/{property_id}/tax_bills/{tax_bill_id}/deferral_plans/{deferral_plan_id}/cancel | Cancel a REQUESTED plan (REQUESTED → DEFAULTED, treated as cancellation). | Owner |
| GET | /properties/{property_id}/tax_bills/{tax_bill_id}/deferral_plans/{deferral_plan_id} | Fetch a `DeferralPlan` with live `accrued_interest`. | Assessor, Treasurer, HearingOfficer, Owner |
| POST | /_clock/advance | Advance the logical clock to `target_timestamp`; runs time-gated auto-transitions. | Assessor, Treasurer, HearingOfficer, Owner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_MISMATCH | 409 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_DUPLICATE_ROLL_YEAR | 409 |
| ERR_APPEAL_WINDOW_CLOSED | 409 |
| ERR_HEARING_INTERVAL_INVALID | 422 |
| ERR_ROOM_DOUBLE_BOOKED | 409 |
| ERR_OFFICER_BUFFER_VIOLATED | 409 |
| ERR_BOE_OFFICER_CONFLICT | 403 |
| ERR_OFFICER_MISMATCH | 403 |
| ERR_DECISION_VALUE_INCONSISTENT | 422 |
| ERR_EXEMPTION_DUPLICATE | 409 |
| ERR_EXEMPTION_INELIGIBLE | 422 |
| ERR_OVERPAYMENT | 409 |
| ERR_DUPLICATE_BILL | 409 |
| ERR_ASSESSMENT_NOT_FINALIZED | 409 |
| ERR_EXEMPTIONS_PENDING | 409 |
| ERR_DEFERRAL_NOT_ELIGIBLE | 422 |
| ERR_VALIDATION_FAILED | 400 |
