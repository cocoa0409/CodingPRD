# GLP-1 Weight-Loss Telehealth API — Product Requirements Document

## 1. Introduction

Weight-loss medicine delivered over video has become an operations problem long before it becomes a clinical one. A member fills in an intake form; a lab panel arrives days later and may already be too old to act on; a clinician has fifteen minutes to decide whether the member qualifies; a molecule that is chronically short must be routed to whichever compounding or branded pharmacy can legally ship into the member's state with a lot that has not yet expired; a payer may or may not agree to cover any of it; and the member is billed every thirty days on a subscription that can be paused, resumed, cancelled or reversed. Each of those steps is owned by a different operator, and every one of them can invalidate a decision another operator has already made.

This document specifies the backend service that holds that programme together. The service is mounted under `/glp1` and exposes a flat collection of peer resources — members, clinicians and coaches, pharmacies and their physical stock, eligibility screenings, consults, prescriptions, titration rungs, prior authorisations, pharmacy orders, subscriptions, billing cycles, side-effect check-ins and coaching sessions. Nothing is nested in the URL space; relationships are carried by identifier fields on the resources themselves, which means the service — not the client — is responsible for keeping related records consistent when any one of them moves.

Three design commitments run through everything that follows. First, **frozen decisions stay frozen**: an eligibility screening captures the body measurements it was adjudicated on, and a later weigh-in never rewrites it. Second, **every compensating action restores exactly what its forward action took**: cancelling a reservation must return the same units to the same lot, cancelling a coaching booking must return the same credit to the same pool, and reversing a settlement must be visible as a credit rather than as an erased charge. Third, **the clinical axis and the fulfilment axis of a prescription move independently**: a member whose therapy is frozen for vomiting still has a shipment in flight, and the service must model both truths at once rather than collapsing them into a single status.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Identity and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity the caller is acting in. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (401). The six roles are `Patient`, `Provider`, `Coach`, `PharmacyOperator`, `BillingAdmin` and `PlatformAdmin`. When a well-formed, recognised role attempts an operation that role is not authorised for, the rejection is `ERR_UNAUTHORIZED` (403).

Four of the six roles are entity-backed, meaning `X-User-ID` names a row that already exists in the system, and ownership checks compare a field on the target resource against that identifier:

- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting Patient; ownership checks on any resource that references a Patient compare the resource's patient-identifier field to `X-User-ID`.
- When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting Provider; ownership checks compare the resource's `provider_id`, `prescriber_provider_id` or `triaged_by_provider_id` to `X-User-ID`, depending on which relationship the operation depends on.
- When `X-User-Role` is `Coach`, `X-User-ID` is likewise the `id` of a Provider row — specifically one whose `provider_type` is `COACH` — and ownership checks compare a coaching session's `coach_provider_id` to `X-User-ID`.
- When `X-User-Role` is `PharmacyOperator`, `X-User-ID` is the `id` of the acting Pharmacy; ownership checks compare a pharmacy order's `pharmacy_id` to `X-User-ID`.

The remaining two roles are opaque. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is an operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The same is true when `X-User-Role` is `PlatformAdmin`: the value identifies an operations administrator and is not matched against any row.

Ownership is enforced on six operations in particular — closing a consult, discontinuing a prescription, reserving a pharmacy order, shipping a pharmacy order, completing a coaching session, and cancelling a subscription. On these six, a caller whose role is listed for the endpoint but who is not the owner of the target row is still rejected with `ERR_UNAUTHORIZED` (403).

A note on segregation of duties, expanded in §3.5: the Provider recorded as a prescription's `prescriber_provider_id` may not act as the second signing clinician on that same prescription's high-dose escalations.

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

### 2.3. Pagination and List Retrieval

Every list endpoint accepts two pagination query parameters. The `limit` parameter caps the number of records returned; it defaults to 10, may be no smaller than 1 and no larger than 100. The `offset` parameter skips that many records before the page begins; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is a validation failure and is rejected with `ERR_VALIDATION` (400).

Unless a specific endpoint states otherwise, list results are ordered by the record's creation timestamp, ascending. List responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope; `total_count` reflects the number of records matching the filters before pagination is applied, and `has_more` is true when records remain beyond the current page.

Most list endpoints also accept filters that narrow the collection. Every list endpoint in the system accepts a `status` filter matching the corresponding resource's own status enumeration, with two exceptions: prescriptions are filtered by `clinical_status` and `fulfillment_status` separately because they carry two independent status axes, and the check-in list additionally accepts `triaged_by_provider_id`. The remaining filters are relationship filters — `patient_id`, `provider_id`, `pharmacy_id`, `prescription_id`, `consult_id`, `prescriber_provider_id`, `screening_id`, `supersedes_prescription_id`, `titration_step_id`, `second_signer_provider_id`, `supply_lot_id`, `subscription_id`, `coach_provider_id` and `billing_cycle_id` — each restricting results to records whose corresponding identifier field matches. All filters are optional and combine conjunctively.

### 2.4. The Logical Clock

Nothing in this system reads the host's wall clock. Every window test, expiry comparison, staleness calculation and elapsed-day interval is evaluated against a single server-held **logical clock**. Before any client has moved it, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to real time. A `PlatformAdmin` moves it by calling `POST /glp1/_clock/set_current_utc` with a `to_iso8601` value; the response reports the new setting as `current_utc`. The clock may be advanced or rewound freely, and moving it mutates no entity row.

Whenever this document says "the clock", it means this logical clock. Every system-written timestamp — `submitted_at`, `triaged_at`, `resolved_at`, `decided_at`, `reserved_at`, `shipped_at`, `invoiced_at`, `completed_at`, `administered_at`, `paused_at`, `last_dose_change_at` — is the logical clock's value at the moment the operation succeeded. Elapsed-day arithmetic is always performed by taking the difference between two instants in seconds, dividing by 86,400, and discarding the remainder — that is, whole days, rounded down, never rounded up and never fractional.

### 2.5. Common Resource Properties

Every resource in the system — Patients, Providers, Pharmacies, Supply Lots, Eligibility Screenings, Consults, Prescriptions, Titration Steps, Prior Authorizations, Pharmacy Orders, Subscriptions, Billing Cycles, Check-Ins and Coaching Sessions — carries the same four system-managed fields:

- `id` (string): a server-minted UUID. Identifiers carry no type prefix and are never supplied by the client.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written, taken from the logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the row, including mutations the server performs as a side effect of an operation aimed at a different resource.
- `version` (integer): a counter that begins at 1 and increments by 1 on every mutation of the row.

Because cascades in this system routinely reach across resources, it bears repeating: when the server holds a prescription because a check-in escalated, or cancels a pharmacy order because a payer denied coverage, or forfeits a coaching session because a billing cycle was voided, each touched row has its own `updated_at` refreshed and its own `version` incremented. There is no such thing as a silent side effect.

### 2.6. Left-to-Right Path Resolution and Not-Found Routing

When a request carries a resource identifier in its URL path, that identifier is resolved before any body validation, business rule or state check runs. Resolution proceeds left to right, and the first identifier that fails to resolve determines the 404 that is returned. Identifiers supplied in a request *body* are resolved later — after body-shape validation — but they are routed to the same family of error codes.

Which 404 is returned depends on the collection the missing identifier belongs to. A Patient that does not resolve yields `ERR_PATIENT_NOT_FOUND`. A Provider that does not resolve yields `ERR_PROVIDER_NOT_FOUND` — this covers `provider_id`, `prescriber_provider_id`, `second_signer_provider_id` and `coach_provider_id` alike. A Pharmacy or a Supply Lot yields `ERR_PHARMACY_RESOURCE_NOT_FOUND`. An Eligibility Screening, Consult, Prescription, Titration Step or Check-In yields `ERR_CLINICAL_RECORD_NOT_FOUND`. A Prior Authorization or Pharmacy Order yields `ERR_FULFILLMENT_RECORD_NOT_FOUND`. A Subscription, Billing Cycle or Coaching Session yields `ERR_BILLING_RECORD_NOT_FOUND`. All six carry HTTP status 404.

### 2.7. The Order in Which a Request Is Screened

Rules are evaluated in a strict ascending order, and the first rule that fails determines the response — no later rule runs, and no partial mutation is persisted. Implementers should treat the following ladder as normative wherever two rules could both fire on the same request:

1. **Authentication.** Both headers present, and `X-User-Role` one of the six declared roles — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorisation.** The acting role appears in the endpoint's authorised-role list in §4 — otherwise `ERR_UNAUTHORIZED` (403).
3. **Path existence.** Every identifier in the URL path resolves, left to right, routed to the 404 codes of §2.6.
4. **Ownership.** For entity-backed roles on the six ownership-guarded operations named in §2.1, the acting identifier must own the target row — otherwise `ERR_UNAUTHORIZED` (403).
5. **Body shape.** Every required field is present, every value matches its declared type, every enum value is a declared member, every bounded integer sits inside its range (`nausea_score` and `vomiting_score` from 0 through 3 inclusive; `units_per_cycle` and `units_requested` from 1 through 4 inclusive; `limit` from 1 through 100; `offset` at least 0), every interval's end instant is strictly after its start instant, and `npi` is present whenever `provider_type` is `CLINICIAN` — otherwise `ERR_VALIDATION` (400).
6. **Body reference existence.** Every foreign identifier supplied in a request body resolves to an existing row, routed to the 404 codes of §2.6. This applies to the nine creation operations that carry references: opening a screening, booking a consult, issuing a prescription, filing a prior authorisation, creating a pharmacy order, starting a subscription, filing a check-in, booking a coaching session, and recording a supply lot.
7. **Optimistic concurrency.** The version expectations described in §2.8 — `ERR_STALE_PATIENT_VERSION` or `ERR_STALE_PRESCRIPTION_VERSION`, both 412.
8. **State admissibility.** The target row is in a state from which the requested transition is declared (`ERR_INVALID_STATE`, 409); where an operation additionally demands that the governing prescription be clinically active, a `HELD` or `DISCONTINUED` prescription yields `ERR_PRESCRIPTION_NOT_ACTIVE` (409); where it demands an active subscription, a `PAUSED` or `CANCELLED` subscription yields `ERR_SUBSCRIPTION_NOT_ACTIVE` (409).
9. **Clinical safety gates.** Screening eligibility, open escalations, dose ceilings, second-signer rules, titration intervals and prior-authorisation coverage, detailed in §3.
10. **Practitioner suitability.** The clinician or coach named on the request is of the right type, is not suspended, and — for consults — is licensed in the member's state (`ERR_PROVIDER_NOT_ELIGIBLE`, 422).
11. **Calendar collisions and window placement.** Consult and coaching slot conflicts, and the resolution of a coaching session into a billing cycle window.
12. **Supply and quota constraints.** Lot routing, per-order unit ceilings, windowed lot capacity, and the appeal ceiling.
13. **Entitlement and fiscal ceilings.** Coaching credit exhaustion and the cumulative pause ceiling.

Where several rules share a rung of this ladder, the narrative in §3 pins their relative order for the operation concerned.

`ERR_PRESCRIPTION_NOT_ACTIVE` guards exactly five operations: creating a pharmacy order, reserving a pharmacy order, shipping a pharmacy order, escalating a titration rung, and requesting a refill. `ERR_SUBSCRIPTION_NOT_ACTIVE` guards exactly four: booking a coaching session, completing a coaching session, invoicing a billing cycle, and settling a billing cycle.

### 2.8. Optimistic Concurrency on the Chart and on the Prescription

Two write operations in this system read a parent record, make a decision that depends on what they read, and then write a child record that supersedes or reroutes something. Both require the caller to prove it saw the parent as it currently stands.

**Issuing a prescription.** A `POST /glp1/prescriptions` request must carry `expected_patient_version`, a non-optional integer field holding the client's last observed `version` of the Patient named by `patient_id`. If that value does not equal the Patient's current `version`, the request is rejected with `ERR_STALE_PATIENT_VERSION` (412). This matters because a new prescription legitimately supersedes the member's standing active prescription, and the server cannot otherwise distinguish a deliberate replacement from a clinician acting on a chart that has since changed — a vitals update or a screening decision landing in between both advance the Patient's `version`.

**Creating a pharmacy order.** A `POST /glp1/pharmacy-orders` request must carry `expected_prescription_version`, a non-optional integer field holding the client's last observed `version` of the Prescription named by `prescription_id`. If that value does not equal the Prescription's current `version`, the request is rejected with `ERR_STALE_PRESCRIPTION_VERSION` (412). Routing reads `active_route_mode`, `dose_mg` and `dose_level`, and every one of those moves when a payer decision lands or a titration rung is escalated; a caller holding an older version would route on a superseded dose or on the wrong pricing fork.

No other endpoint accepts a version expectation field. Endpoints not named above take no version input and perform no concurrency check.

### 2.9. Money, Counts and Rounding

All monetary amounts in this system are integers denominated in whole cents; there are no fractional-cent values anywhere in a request or a response, and no currency strings. Wherever a monetary computation produces a fraction — a percentage discount, a coinsurance share, a prorated slice of a cycle — the result is rounded to the nearest whole cent using the round-half-up convention, meaning a value exactly halfway between two cents rounds away from zero to the larger cent.

Two rounding *orders* are pinned and must not be rearranged, because they change the answer:

- In per-cycle drug pricing, the per-unit price is rounded to whole cents **before** it is multiplied by the number of units in the cycle, never after.
- In proration, each charge component is prorated and rounded to whole cents **separately**, and only then are the rounded components summed; the sum is never rounded a second time.

Body-mass index is the one non-monetary quantity that carries a rounding rule: it is rounded to exactly one decimal place, again half-up, and every threshold comparison is made against the *rounded* value rather than the raw quotient. Credit counts, unit counts, severity scores and day counts are integers throughout and are never rounded because they are never fractional.

### 2.10. Conservation Guarantees

Three quantities in this system are conserved. Each has a forward action that moves a quantity from one bucket to another and a compensating action that moves it back, and each identity must hold at every observable point — not merely after a workflow completes.

**Supply-lot unit conservation (INV-1).** For every supply lot, `total_units` always equals `available_units` plus `reserved_units` plus `dispensed_units`. Reserving a pharmacy order moves `units_requested` from `available_units` to `reserved_units`; cancelling that order while it is reserved moves exactly the same quantity back from `reserved_units` to `available_units`, restoring both components to their pre-reservation values rather than merely restoring the sum. Shipping moves the same quantity from `reserved_units` to `dispensed_units`, which is permanent — dispensed units never return.

**Coaching credit conservation (INV-2).** For every subscription, `coaching_credits_granted` always equals `coaching_credits_available` plus `coaching_credits_reserved` plus `coaching_credits_consumed` plus `coaching_credits_forfeited`. Booking a session moves one credit from available to reserved; cancelling that booking moves the same credit from reserved back to available. Completing the session moves it from reserved to consumed. Forfeiture is deliberately *not* a compensating action: it moves the credit from reserved to forfeited, which preserves the identity while permanently removing the credit from availability.

**Member billing conservation (INV-3).** For every member, `lifetime_charged_cents` minus `lifetime_credited_cents` always equals the sum of `settled_amount_cents` across that member's billing cycles that are currently settled. Settling a cycle adds its `settled_amount_cents` to `lifetime_charged_cents`; voiding a settled cycle adds the same pre-void amount to `lifetime_credited_cents` and then zeroes `settled_amount_cents`. Voiding a cycle that was merely open or invoiced touches neither lifetime counter, because nothing was ever collected — which is why the pause and cancellation cascades preserve the identity as well.

### 2.11. Status Codes

Operations that bring a new resource into existence return `201 Created`. Every other successful operation — state transitions, recalculations, clock movements and reads — returns `200 OK`. Error responses carry the HTTP status listed against their error identifier in §5.

## 3. Business Logic & Workflows

### 3.1. Enrolment, the Clinical Directory and Physical Stock

A `PlatformAdmin` seeds the programme. Enrolling a member records an `email` (which must contain an at-sign and must be unique across all members — a duplicate or malformed address is rejected with `ERR_VALIDATION`), a `full_name`, a `state_code` of exactly two upper-case letters naming the state of residence, a `height_cm` and a `weight_kg`, both of which must be strictly greater than zero, and a `payment_mode` of either `INSURANCE` or `CASH` describing how the programme intends to bill this member. An optional `comorbidity_codes` array may be supplied; when omitted it defaults to the empty list. Each element must be one of `TYPE_2_DIABETES`, `HYPERTENSION`, `DYSLIPIDEMIA`, `OSA` or `CVD`, and the list may not repeat a code.

Three derived values are written at enrolment and are visible on every read of the member. `current_bmi` is the member's live body-mass index; `eligibility_status` starts at `NOT_SCREENED`; and the two lifetime billing counters, `lifetime_charged_cents` and `lifetime_credited_cents`, both start at zero. The body-mass index is computed by converting the height from centimetres to metres — dividing `height_cm` by 100 — squaring that figure, dividing `weight_kg` by the square, and rounding the quotient half-up to exactly one decimal place. This is the **current-recheck** reading of body-mass index: it always reads the member's live `height_cm` and `weight_kg`, so it drifts as the member's weight changes.

That drift is the point. A member or their clinician may record a new weigh-in at any time by submitting a fresh `weight_kg`; the service recomputes `current_bmi` on the spot from the new weight and the unchanged height, refreshes `updated_at`, and increments the member's `version`. That version bump is not cosmetic — it invalidates any `expected_patient_version` a clinician captured before the weigh-in, which is exactly the serialisation point §2.8 describes. Notably, `current_bmi` gates nothing. It is a chart-review figure. The gate that decides whether therapy may begin reads a *different*, frozen number, described in §3.2, and the two are permitted to disagree without blocking care.

Clinicians and coaches are registered as a single kind of directory record distinguished by `provider_type`, which is either `CLINICIAN` or `COACH`. Each carries a `full_name`, a `licensed_state_codes` array of two-letter state codes (defaulting to the empty list) naming where that practitioner may see members, and a `status` of `ACTIVE` or `SUSPENDED` that defaults to `ACTIVE`. An `npi` — the national provider identifier — is mandatory when `provider_type` is `CLINICIAN`; a request registering a clinician without one is rejected with `ERR_VALIDATION`. For a coach the field is ignored and defaults to null.

Dispensing pharmacies are registered with a `name`, a `dispense_type` of either `COMPOUNDED` or `BRANDED` declaring which product form they supply, a `served_state_codes` array of the states they may ship into (defaulting to the empty list), and a `status` of `ACTIVE` or `SUSPENDED` that defaults to `ACTIVE`. A pharmacy dispenses one form and one form only; there are no mixed pharmacies.

Physical stock is recorded as **supply lots**. A lot names its holding pharmacy through `pharmacy_id`, carries the compounder's or manufacturer's `lot_code`, a `strength_mg` strictly greater than zero giving the milligram strength of every unit in the lot, a `total_units` count of at least zero, a `window_capacity_units` figure of at least zero that caps how many units the lot may have committed across any set of overlapping shipping windows, an `expires_at` instant, and a `status` of either `RELEASED` or `QUARANTINED` that defaults to `RELEASED`. When the lot is recorded, `available_units` is initialised to `total_units` while `reserved_units` and `dispensed_units` both start at zero — the opening position of the conservation identity described in §2.10. Lots may be read individually or listed, and the list is the operator's window onto how much of a lot is free, held and gone.

### 3.2. Eligibility Screening and the Re-Screen Cycle

Before anyone may be prescribed a GLP-1 agonist, a screening must adjudicate them. A member or a clinician opens one by naming the `patient_id` and supplying the lab and anthropometric evidence: a `recorded_weight_kg` strictly greater than zero, an `egfr` of at least zero from the renal panel, a `lab_collected_at` instant recording when the specimen was drawn, and optionally an `a1c_pct` which defaults to null when not supplied. At the moment the screening row is created the service snapshots the member's `height_cm` into `recorded_height_cm`; that snapshot never moves again, no matter what later weigh-ins do to the chart. A newly opened screening sits in `DRAFT` with `assessed_bmi`, `eligibility_band` and `decision_reason` all null, `submitted_at` null, `submit_count` at zero and `comorbidity_count` at zero.

Adjudication happens when a `Provider` submits the screening. The submission may carry fresh values for `recorded_weight_kg`, `egfr`, `a1c_pct` and `lab_collected_at`; any field supplied overwrites the stored one *before* the decision runs, and any field omitted leaves the stored value in place. The service then freezes a body-mass index into `assessed_bmi` using the **screening-snapshot** reading: the same centimetres-to-metres conversion, square, divide and round-half-up-to-one-decimal-place arithmetic as §3.1, but computed from `recorded_weight_kg` and `recorded_height_cm` rather than from the live chart. Once frozen it is never recomputed by a later weigh-in. It also counts the entries currently in the member's `comorbidity_codes` and writes that count into `comorbidity_count`, sets `submitted_at` to the clock, and increments `submit_count` by one.

The decision itself follows a pinned, total ladder; the first clause that matches wins and no later clause is consulted.

1. **Stale labs.** The age of the labs in whole days is the difference between the clock and `lab_collected_at` in seconds divided by 86,400 with the remainder discarded. If that age is 90 days or more, the screening lands in `DEFERRED` with `decision_reason` set to `STALE_LABS`. On this branch `assessed_bmi` and `eligibility_band` are both left null — no clinical reading is produced from evidence too old to trust — while `submitted_at` and `submit_count` are still updated.
2. **Renal exclusion.** Otherwise, if `egfr` is below 30.0, the screening lands in `INELIGIBLE` with `decision_reason` set to `RENAL_EXCLUSION`. Because this clause is evaluated *before* the body-mass tests, a member who fails both the renal panel and the weight bands reports `RENAL_EXCLUSION`, never `BMI_BELOW_BAND`.
3. **Obesity band.** Otherwise, if the frozen `assessed_bmi` is at least 30.0, the screening lands in `ELIGIBLE` with `eligibility_band` set to `OBESITY` and `decision_reason` set to `BMI_QUALIFIED`.
4. **Comorbid band.** Otherwise, if the frozen `assessed_bmi` is at least 27.0 *and* `comorbidity_count` is at least 1, the screening lands in `ELIGIBLE` with `eligibility_band` set to `COMORBID` and `decision_reason` set to `COMORBID_QUALIFIED`.
5. **Below band.** Otherwise the screening lands in `INELIGIBLE` with `decision_reason` set to `BMI_BELOW_BAND`.

On both `INELIGIBLE` branches — renal exclusion and below-band alike — `eligibility_band` is written as `NONE`. A member excluded on renal grounds therefore shows `NONE` even when their frozen body-mass index would, on its own, have qualified them; the band field records the band the programme is willing to act on, not the band the arithmetic produced.

Every submission mirrors its outcome onto the member: `eligibility_status` on the Patient row is set to `ELIGIBLE`, `INELIGIBLE` or `DEFERRED` to match, and the member's `version` is incremented by one. Clinicians who intend to prescribe should therefore re-read the member after a submission, because the mirror bump invalidates any previously captured `expected_patient_version`.

Deferral is not a dead end — it is a loop. A screening in `DEFERRED` may be resubmitted any number of times. If the resubmission supplies a `lab_collected_at` that is still 90 days old or older, the screening simply stays `DEFERRED`: `submit_count` rises by one, `submitted_at` refreshes, and both the status and the `STALE_LABS` reason are left where they were. If the resubmission supplies fresh labs and the renal and band tests pass, the screening advances `DEFERRED → ELIGIBLE`, freezing `assessed_bmi` and `eligibility_band` exactly as the first-time path does and incrementing `submit_count`. If fresh labs arrive but `egfr` is below 30.0 or the band test fails, it advances `DEFERRED → INELIGIBLE` with the same side effects the first-time ineligible path produces, `submit_count` again rising by one. `ELIGIBLE` and `INELIGIBLE` are terminal: a submission aimed at a screening already resting in either is rejected with `ERR_INVALID_STATE` (409).

### 3.3. Booking, Closing and Rescheduling the Telehealth Consult

A member books a consult by naming their own `patient_id`, the `provider_id` of the clinician they want, and the window: `scheduled_start_at`, which is inclusive, and `scheduled_end_at`, which is exclusive and must be strictly after the start. A new consult opens in `SCHEDULED` with `outcome_note` null and `reschedule_count` at zero.

Two gates guard the booking, and their order is fixed. First the clinician is checked for suitability: the named practitioner must have `provider_type` `CLINICIAN`, must have `status` `ACTIVE`, and must list the member's `state_code` among their `licensed_state_codes`. A practitioner failing any of those three tests is rejected with `ERR_PROVIDER_NOT_ELIGIBLE` (422). Only if the clinician is suitable does the calendar test run.

The calendar test is a buffered overlap check against every *other* consult of the same clinician that is currently in `SCHEDULED`; consults in any other status are invisible to it. The programme insists on a fifteen-minute turnaround between telehealth appointments, and it enforces this by widening both sides before testing. A collision exists when the new consult's `scheduled_start_at` falls earlier than the other consult's `scheduled_end_at` plus fifteen minutes, *and* the other consult's `scheduled_start_at` falls earlier than the new consult's `scheduled_end_at` plus fifteen minutes. Both conditions must hold for a collision; if either fails there is no collision. A collision is rejected with `ERR_CONSULT_SLOT_CONFLICT` (409). Because both sides are widened, two consults that merely abut — one ending exactly when the next begins — do collide, and so do two separated by anything less than the full buffer.

The consult's own clinician closes it, supplying an `outcome` of `PRESCRIBE`, `DECLINE` or `NO_SHOW` and an optional `outcome_note` that is recorded on the row. Only the clinician named as the consult's `provider_id` may close it; anyone else is turned away under the ownership rule of §2.1. A `PRESCRIBE` outcome moves the consult `SCHEDULED → COMPLETED_PRESCRIBED` and additionally requires that the member's `eligibility_status` currently read `ELIGIBLE`; closing a consult as prescribing for a member who is `NOT_SCREENED`, `INELIGIBLE` or `DEFERRED` is rejected with `ERR_INVALID_STATE` (409). A `DECLINE` outcome moves the consult `SCHEDULED → COMPLETED_DECLINED`; the note is recorded and no prescription may ever cite that consult. A `NO_SHOW` outcome moves it `SCHEDULED → NO_SHOW`. All three outcomes release the clinician's slot immediately, which is to say the closed consult stops participating in the buffered overlap test and a later consult may occupy the same window.

A no-showed consult can be brought back. Rescheduling moves it `NO_SHOW → SCHEDULED` at a new `scheduled_start_at` and `scheduled_end_at`, re-running both the clinician-suitability test and the same fifteen-minute buffered overlap test against the clinician's other `SCHEDULED` consults, and incrementing `reschedule_count` by one. There is no ceiling on this: a consult may bounce between `SCHEDULED` and `NO_SHOW` indefinitely, and `reschedule_count` simply records how often it has. `COMPLETED_PRESCRIBED` and `COMPLETED_DECLINED` are terminal — a reschedule aimed at either is rejected with `ERR_INVALID_STATE` (409).

### 3.4. Issuing a Prescription and Its Two Independent Axes

A prescription is issued by a `Provider` off the back of a prescribing consult and an eligible screening. The request names the `patient_id`, the `consult_id` of the consult that authorised it, the `prescriber_provider_id` of the clinician of record, the `screening_id` of the frozen screening whose band gates the issue, a `drug_family` of either `SEMAGLUTIDE` or `TIRZEPATIDE`, and the `expected_patient_version` described in §2.8. An optional `units_per_cycle` states how many pens are dispensed per thirty-day cycle; it must be an integer from 1 through 4 inclusive and defaults to 4 when omitted.

The eligibility gate reads the *frozen* screening, never the live chart. The cited screening must currently be in `ELIGIBLE` status and must name the same `patient_id` as the prescription request; a screening that is `DRAFT`, `DEFERRED` or `INELIGIBLE`, or one belonging to a different member, is rejected with `ERR_SCREENING_NOT_ELIGIBLE` (409). This is the reason §3.1 insists that `current_bmi` gates nothing: a member who has since lost enough weight to drop below 27.0 still holds a valid frozen band and may still be prescribed. The cited consult must have closed as `COMPLETED_PRESCRIBED`; a request naming a consult that closed `COMPLETED_DECLINED`, or one still in `SCHEDULED` or `NO_SHOW`, is rejected with `ERR_INVALID_STATE` (409).

A newly issued prescription is seeded as follows. Its `dose_level` is 1 and its `dose_mg` is rung 1 of the ladder for the chosen `drug_family`, taken from the table in §3.5. Its `last_dose_change_at` is set to the clock — this is the baseline every later titration interval is measured from. Its `active_route_mode` is seeded from the member's `payment_mode`, so an `INSURANCE` member's prescription starts on the insurance fork and a `CASH` member's starts on the cash fork. Both severity indices, `severity_index_rolling` and `severity_index_since_dose_change`, start at zero, and `discontinue_reason` starts null. The service also creates the first titration rung — `step_number` 1, status `DUE` — as described in §3.5, and increments the member's `version` by one.

Every prescription carries **two status axes that advance independently**, and neither constrains the other's value. The clinical axis, `clinical_status`, is one of `ACTIVE`, `HELD` or `DISCONTINUED` and begins at `ACTIVE`. The fulfilment axis, `fulfillment_status`, is one of `UNROUTED`, `ROUTED`, `DISPENSED` or `REFILL_DUE` and begins at `UNROUTED`. A prescription frozen on the clinical axis keeps whatever value it had on the fulfilment axis; nothing about a hold rewinds fulfilment. The combined opening position is therefore clinically `ACTIVE` and fulfilment-wise `UNROUTED`.

The fulfilment axis moves like this. Routing a fill advances it `UNROUTED → ROUTED` and also increments the prescription's `version` by one. Creating a *further* fill while the axis already reads `ROUTED` is explicitly not a state error: the axis simply stays at `ROUTED`, which is what allows a single titration rung to carry several open orders against different lots or different shipping windows. Shipping a reserved order advances the axis `ROUTED → DISPENSED`. A member or clinician may then request a refill, advancing it `DISPENSED → REFILL_DUE`; this requires the axis to currently read `DISPENSED` and requires the clinical axis to read `ACTIVE`, and a held or discontinued prescription is refused with `ERR_PRESCRIPTION_NOT_ACTIVE` (409). Routing the refill closes the loop by moving the axis `REFILL_DUE → ROUTED`. Finally, cancelling a *reserved* order rewinds the axis to `UNROUTED`, but only when no other order for that prescription remains in `CREATED` or `RESERVED`.

Supersession is automatic and self-referential. A prescription's `supersedes_prescription_id` is null unless it displaced a predecessor. When a prescription is issued for a member who already holds a prescription whose `clinical_status` is `ACTIVE`, that standing prescription is discontinued as a side effect of the issue: its `clinical_status` moves `ACTIVE → DISCONTINUED`, its `discontinue_reason` is set to `SUPERSEDED`, the new prescription's `supersedes_prescription_id` is set to the superseded prescription's `id`, and every pharmacy order of the superseded prescription still sitting in `CREATED` or `RESERVED` is cancelled with `cancel_reason` `CLINICAL_HOLD` — which, for the reserved ones, returns their units to the lot's `available_units` under §2.10. Supersession does **not** touch the superseded prescription's titration rungs.

Explicit discontinuation is the other way out, and it does more. A `Provider` or the member themselves may end a prescription, supplying a `discontinue_reason` of `PATIENT_REQUEST`, `CLINICAL` or `SUPERSEDED`. The transition is permitted from either `ACTIVE` or `HELD` — only an already-`DISCONTINUED` prescription refuses it, with `ERR_INVALID_STATE` (409). The reason from the request body is recorded; every pharmacy order for that prescription in `CREATED` or `RESERVED` is cancelled with `cancel_reason` `CLINICAL_HOLD`, releasing any reserved units back to the lot; and — unlike the supersession path — every titration rung of that prescription in `DUE` or `HELD` is moved to `REDUCED` with its `administered_at` set to the clock. `DISCONTINUED` is terminal on the clinical axis.

### 3.5. Climbing and Descending the Titration Ladder

Dose escalation in this programme is a ladder of exactly five rungs, and the milligram strength at each rung depends on the molecule. For `SEMAGLUTIDE` the ladder runs 0.25 mg at rung 1, 0.5 mg at rung 2, 1.0 mg at rung 3, 1.7 mg at rung 4 and 2.4 mg at rung 5. For `TIRZEPATIDE` it runs 2.5 mg at rung 1, 5.0 mg at rung 2, 7.5 mg at rung 3, 12.5 mg at rung 4 and 15.0 mg at rung 5. This is an exact table lookup with no rounding and no interpolation: whenever a prescription's `dose_level` changes, its `dose_mg` is re-read from the table for its `drug_family` at the new level. The lookup is consulted at three moments — when a prescription is created, when a rung is escalated, and when a rung is reduced. Rung 5 is the top of the ladder.

Titration rungs are never created directly by a client; the service creates them and the rung list is the only channel through which they are discovered. Each rung records the `prescription_id` it belongs to, a `step_number` giving its 1-based ordinal within that prescription, the `dose_level` it administers and the corresponding `dose_mg`, a `status` of `DUE`, `ADMINISTERED`, `HELD` or `REDUCED` that begins at `DUE`, an `earliest_escalation_at` planning date, an `administered_at` instant that starts null, a `hold_reason` that starts null, and a `second_signer_provider_id` that starts null.

The `earliest_escalation_at` field is a **planning view and never a gate**. Whenever a rung row is created, it is set to that rung's `created_at` plus 28 days, flat, ignoring the member's side-effect history entirely. The rule that actually decides whether an escalation may proceed is stricter and reads history, so an escalation can legitimately be refused on a date that `earliest_escalation_at` already permits. That gap is intentional and clients should treat the planning date as advisory.

**Escalating.** A `Provider` steps the ladder up one rung, optionally supplying a `second_signer_provider_id`. The rung must be in `DUE`; an escalation aimed at a rung in any other status is rejected with `ERR_INVALID_STATE` (409). The governing prescription must be clinically `ACTIVE`; a `HELD` or `DISCONTINUED` prescription is refused with `ERR_PRESCRIPTION_NOT_ACTIVE` (409). Beyond that, five clinical gates are evaluated in this exact order, and the first to fail determines the response:

1. **No open escalation.** If any check-in for that prescription is still in `ESCALATED` status, the request is refused with `ERR_OPEN_ESCALATED_CHECK_IN` (409).
2. **Ladder ceiling.** If the prescription's `dose_level` is already 5, there is no rung above it and the request is refused with `ERR_TITRATION_MAX_DOSE_REACHED` (422). Equivalently, escalation requires the current `dose_level` to be strictly less than 5.
3. **Second signer present.** The target level is the current `dose_level` plus one. If the target level is 4 or 5, a `second_signer_provider_id` must be supplied; its absence is refused with `ERR_SECOND_SIGNER_REQUIRED` (422). Below that target level the field is optional and, when supplied, is simply recorded.
4. **Second signer admissible.** When a second signer is supplied, it must differ from the prescription's `prescriber_provider_id`, must name a practitioner whose `provider_type` is `CLINICIAN`, and must name one whose `status` is `ACTIVE`. Any of those three failing is refused with `ERR_SECOND_SIGNER_CONFLICT` (403). This is the programme's segregation-of-duties rule: the clinician of record cannot co-sign their own member onto the two highest rungs.
5. **Interval.** The elapsed time since the prescription's `last_dose_change_at`, taken in whole days by dividing the difference in seconds by 86,400 and discarding the remainder, must reach the required interval. The requirement is normally 28 days, but it stretches to 42 days whenever the prescription's `severity_index_since_dose_change` has reached 4 or more — a member who has been struggling since their last increase waits half again as long. In both cases the comparison is inclusive: elapsed days *equal to* the requirement are sufficient. A shortfall is refused with `ERR_TITRATION_INTERVAL_NOT_MET` (409).

A successful escalation moves the rung `DUE → ADMINISTERED`, sets its `administered_at` to the clock and records the `second_signer_provider_id` when one was supplied. On the prescription it increments `dose_level` by one, re-reads `dose_mg` from the ladder table at the new level, and sets `last_dose_change_at` to the clock. It then recomputes **both** severity indices against the current clock; because the since-last-dose-change window's baseline has just moved to now, `severity_index_since_dose_change` necessarily resets to zero, while `severity_index_rolling` is recomputed over its own thirty-day window and may well stay high. Finally it creates the next rung in `DUE` status with `step_number` one greater, at the new `dose_level` and `dose_mg`, and with `earliest_escalation_at` set to the clock plus 28 days.

**Holding.** A `Provider` may freeze a rung on clinical judgement without changing the dose at all. This moves the rung `DUE → HELD` and sets `hold_reason` to `PROVIDER_HOLD`. It is permitted while the governing prescription is either `ACTIVE` or `HELD`. No `dose_level` change occurs, no `last_dose_change_at` is written, and no new rung is created. A provider hold is not automatically undone by anything: the resolve cascade of §3.8 lifts only holds whose `hold_reason` is `SIDE_EFFECT`.

**Reducing.** A `Provider` may step the ladder down one rung from either `DUE` or `HELD`, in both cases moving the rung to `REDUCED`. Reduction requires no second signer and no interval wait — this is the escape hatch for a member who cannot tolerate their current dose. It is permitted while the governing prescription is `ACTIVE` or `HELD`, and it requires the prescription's `dose_level` to be strictly greater than 1; an attempt to reduce below the bottom rung is rejected with `ERR_INVALID_STATE` (409). A successful reduction sets the rung's `administered_at` to the clock, decrements the prescription's `dose_level` by one, re-reads `dose_mg` at the reduced level, sets `last_dose_change_at` to the clock, and creates the next rung in `DUE` status at the reduced level with `earliest_escalation_at` set to the clock plus 28 days. Both the `DUE → REDUCED` and the `HELD → REDUCED` paths produce exactly these side effects.

`ADMINISTERED` and `REDUCED` are terminal rung statuses.

### 3.6. Payer Coverage: Authorisation, Denial, Appeal and the Cash Fallback

An insured member's therapy is only insured if the payer says so. A `Provider` files a prior authorisation by naming the `prescription_id` and the payer-side case number, `payer_reference`. The filing lands in `SUBMITTED` with `appeal_count` at zero, `decided_at` null, `denial_reason` null and `approved_through_at` null.

A `BillingAdmin` records the payer's answer, supplying a `decision` of either `APPROVED` or `DENIED` together with an optional `denial_reason` carrying the payer's text. Either decision requires the governing prescription's `clinical_status` to be `ACTIVE` or `HELD`; a decision recorded against a `DISCONTINUED` prescription is rejected with `ERR_INVALID_STATE` (409).

**Approval** moves the authorisation `SUBMITTED → APPROVED` (or `APPEALED → APPROVED`, with identical effects). It sets `decided_at` to the clock and `approved_through_at` to the clock plus 180 days — roughly a six-month coverage horizon, after which the approval is stale for shipping purposes even though the status still reads `APPROVED`. It also forces the prescription's `active_route_mode` to `INSURANCE`, regardless of what it was before, and increments the prescription's `version` by one. `APPROVED` is terminal.

**Denial** moves the authorisation `SUBMITTED → DENIED` (or `APPEALED → DENIED`, with identical effects) and sets off a three-hop cascade. Hop one sets `decided_at` to the clock and records the supplied `denial_reason`. Hop two flips the prescription's `active_route_mode` to `CASH` — the member is not abandoned, they are moved onto the self-pay fork, which changes both their pricing and the product form they will be routed to — and increments the prescription's `version` by one. Hop three cancels every pharmacy order for that prescription whose `dispense_type_at_route` is `BRANDED` and whose status is `CREATED` or `RESERVED`, setting each one's `cancel_reason` to `PA_DENIED`; for the reserved ones this in turn returns their held units from the lot's `reserved_units` to its `available_units`. Compounded orders are left alone, because the cash fork can still be filled from them.

**Appeal** is the member's second and third bite. A `Provider` appeals a denial, moving the authorisation `DENIED → APPEALED`; the request may carry a replacement `payer_reference`. The appeal increments `appeal_count` by one and clears both `decided_at` and `denial_reason`, putting the case back in front of the payer with no recorded decision. Appeals are capped: a prescription may be appealed at most twice, so an appeal filed when `appeal_count` has already reached 2 is rejected with `ERR_APPEAL_LIMIT_REACHED` (422). Note that the check is on the count *before* the increment — an appeal is admissible only while `appeal_count` is strictly less than 2. The cycle `DENIED → APPEALED → DENIED` may therefore run twice before the case is exhausted, and each fresh denial repeats the full three-hop cascade including the re-flip to `CASH` and the cancellation of any newly created branded orders.

### 3.7. Fulfilment: Routing, Reservation, Shipment and Cancellation

Filling a prescription begins with a `Provider` creating a pharmacy order that names the `prescription_id`, the `titration_step_id` of the rung whose dose is being dispensed, a `units_requested` count, a shipping window given by an inclusive `window_start_at` and an exclusive `window_end_at` that must be strictly after it, and the `expected_prescription_version` described in §2.8. The order lands in `CREATED` with `reserved_at`, `shipped_at` and `cancel_reason` all null.

The client does **not** choose the pharmacy or the lot. A routing selector runs before the order row is written and picks them, and its output is frozen onto the order for good. The selector first fixes the required product form from the prescription's current `active_route_mode`: an `INSURANCE` prescription requires `BRANDED` product, a `CASH` prescription requires `COMPOUNDED` product. It then assembles the candidate set from every supply lot in the system that satisfies all seven of the following, with no per-pharmacy pre-filter:

- the lot's `status` is `RELEASED` (a `QUARANTINED` lot is never routable);
- the lot's `strength_mg` is exactly equal to the prescription's current `dose_mg` — an exact numeric match, not a nearest-strength match;
- the lot's `available_units` is at least the requested `units_requested`;
- the lot's `expires_at` is at or after the clock plus 30 days, so a lot with less than a month of shelf life left is never shipped;
- the lot's holding pharmacy has `status` `ACTIVE`;
- the lot's holding pharmacy has `dispense_type` equal to the required product form;
- and the member's `state_code` appears in that pharmacy's `served_state_codes`.

Among the survivors the selector ranks first-expiring-first-out: earliest `expires_at` wins. Ties on expiry are broken toward the deepest lot, the one with the largest `available_units`. Ties on both are broken by earliest `created_at`; the lot's `id` is never consulted as a tie-breaker. The winner fixes the order's `pharmacy_id`, its `supply_lot_id` and its `dispense_type_at_route`, and none of the three is ever re-derived afterwards — a later payer denial does not re-route an order, it cancels it. If the candidate set is empty, the request is rejected with `ERR_NO_ELIGIBLE_SUPPLY_LOT` (409).

Two further constraints guard the create, and their order relative to routing is pinned: routing runs first, and only if it produced a lot does the per-order unit ceiling run. That ceiling requires `units_requested` to be at most 4 and also at most the prescription's `units_per_cycle`; a request exceeding either bound is rejected with `ERR_UNITS_EXCEED_LIMIT` (422). Creating an order also requires the prescription's `clinical_status` to be `ACTIVE`, failing which the request is refused with `ERR_PRESCRIPTION_NOT_ACTIVE` (409), and it advances the fulfilment axis as described in §3.4 while incrementing the prescription's `version` by one.

**Reserving.** The operator of the routed pharmacy holds the units. This moves the order `CREATED → RESERVED` and may only be performed by the `PharmacyOperator` whose pharmacy identity matches the order's `pharmacy_id`. The prescription must be clinically `ACTIVE`, failing which the reservation is refused with `ERR_PRESCRIPTION_NOT_ACTIVE` (409). Two stock tests then run. The lot must still hold at least `units_requested` in `available_units`, and the windowed aggregate test must pass: the sum of `units_requested` on this order plus the `units_requested` of every *other* order on the same `supply_lot_id` that is currently `RESERVED` and whose half-open window from `window_start_at` up to but not including `window_end_at` overlaps this order's window must be at most the lot's `window_capacity_units`. Failing either is rejected with `ERR_LOT_CAPACITY_EXCEEDED` (409). A successful reservation sets `reserved_at` to the clock, decrements the lot's `available_units` by `units_requested` and increments its `reserved_units` by the same amount; `total_units` never moves.

**Shipping.** The same pharmacy operator ships a reserved order, moving it `RESERVED → SHIPPED`. The prescription must be clinically `ACTIVE`. One coverage gate applies: when the order's `dispense_type_at_route` is `BRANDED` *and* the prescription's `active_route_mode` is `INSURANCE`, some prior authorisation for that prescription must be in `APPROVED` status with an `approved_through_at` at or after the clock. An expired approval fails this test just as a missing one does, and either is rejected with `ERR_PRIOR_AUTH_REQUIRED` (409). Compounded orders and cash-fork orders skip the gate entirely. A successful shipment sets `shipped_at` to the clock, decrements the lot's `reserved_units` by `units_requested` and increments its `dispensed_units` by the same amount, and advances the prescription's fulfilment axis to `DISPENSED`. `SHIPPED` is terminal.

**Cancelling.** An order that has not shipped may be cancelled, either by the pharmacy operator or by a `Provider`, or automatically as a cascade from a payer denial, a clinical hold or a discontinuation. The two source states behave differently and both behaviours matter. Cancelling from `CREATED` moves the order `CREATED → CANCELLED` and changes no lot counter at all, because nothing had been held yet; it also leaves the prescription's fulfilment axis untouched. Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`, increments the lot's `available_units` by `units_requested` and decrements its `reserved_units` by the same amount — restoring the pre-reservation split exactly, component for component — and additionally rewinds the prescription's `fulfillment_status` to `UNROUTED` when no other order for that prescription remains in `CREATED` or `RESERVED`. On either path, `cancel_reason` is set to `OPERATOR` when a human invoked the cancellation, to `PA_DENIED` when the cascade came from a payer denial, and to `CLINICAL_HOLD` when it came from a clinical hold or a discontinuation. `CANCELLED` is terminal.

### 3.8. Side-Effect Surveillance, Triage and the Clinical Hold Cascade

Nausea, vomiting and dehydration are the reasons members abandon this class of drug, so the programme asks them to report. A member files a check-in naming their own `patient_id` and the `prescription_id` the symptoms relate to, with a `nausea_score` and a `vomiting_score` each an integer from 0 through 3 inclusive, and an optional `dehydration_flag` boolean that defaults to false.

Each report is scored the moment it is filed. The `severity_score` is the `nausea_score` counted once, plus the `vomiting_score` counted twice, plus a flat 4 when `dehydration_flag` is true and nothing when it is false — vomiting weighs double a comparable nausea report, and dehydration alone outweighs maximal nausea. The score is an integer and is never rounded; its full range is 0 through 13. Filing also sets `submitted_at` to the clock. The report lands in `SUBMITTED` with `triaged_by_provider_id`, `triaged_at` and `resolved_at` all null, and — importantly — a report still in `SUBMITTED` counts toward nothing. It is excluded from both prescription severity indices until a clinician has looked at it.

**Triage** is the branch point. A `Provider` triages a submitted report, and the branch is decided purely by the report's own `severity_score`. A `severity_score` strictly below 7 — that is, 6 or lower — moves the report `SUBMITTED → CLEARED`. A `severity_score` of 7 or above moves it `SUBMITTED → ESCALATED`; the threshold comparison is inclusive of 7. Both branches set `triaged_at` to the clock and `triaged_by_provider_id` to the acting clinician, both recompute the prescription's two severity indices, and both count toward the billing cycle's adherence tier described in §3.9.

The branches diverge on what happens to the therapy. A score of 7 or 8 raises the flag and stops there: the report sits `ESCALATED`, the prescription stays `ACTIVE`, and nothing else moves — but while that report remains open, the escalation gate of §3.5 will refuse any dose increase. A score of **9 or above** additionally fires a five-hop cascade. Hop one is the triage itself landing the report in `ESCALATED`. Hop two moves the prescription's `clinical_status` from `ACTIVE` to `HELD`. Hop three moves that prescription's titration rung currently in `DUE` to `HELD` with `hold_reason` set to `SIDE_EFFECT`. Hop four cancels every pharmacy order citing that rung's `titration_step_id` whose status is `CREATED` or `RESERVED`, setting `cancel_reason` to `CLINICAL_HOLD`. Hop five is the stock consequence of hop four: each cancelled reservation returns its `units_requested` from the lot's `reserved_units` to its `available_units`. Every row touched along the chain has its own `updated_at` refreshed and its own `version` incremented.

**Resolution** unwinds it. A `Provider` closes an escalation, moving the report `ESCALATED → RESOLVED` and setting `resolved_at` to the clock. This fires a three-hop cascade of its own, but only under a condition: hop one checks whether any *other* check-in for the same prescription is still in `ESCALATED`. If one is, the therapy stays frozen and nothing further happens. If none is, hop two returns the prescription's `clinical_status` from `HELD` to `ACTIVE`, and hop three returns that prescription's titration rung from `HELD` back to `DUE`, clearing its `hold_reason`. The rung's `earliest_escalation_at` is deliberately left unchanged by this — the hold does not push the planning date out. Note also that hop three lifts only holds whose `hold_reason` was `SIDE_EFFECT`; a rung frozen by a clinician's `PROVIDER_HOLD` stays frozen. `CLEARED` and `RESOLVED` are both terminal check-in statuses.

**The two severity indices.** Each prescription carries two rolling aggregates, and both are recomputed whenever a check-in is triaged and whenever a rung is escalated. Both draw from the same candidate pool — check-ins whose `prescription_id` matches and whose status is `CLEARED`, `ESCALATED` or `RESOLVED` — and both take the single largest `severity_score` in their candidate set, returning zero when the set is empty. What differs is the window:

- `severity_index_rolling` restricts the pool to reports whose `submitted_at` is strictly after the clock minus 30 days and at or before the clock. It knows nothing about dose history.
- `severity_index_since_dose_change` restricts the pool to reports whose `submitted_at` is at or after the prescription's `last_dose_change_at`. A severe report filed before the most recent dose change is therefore invisible to this index while still dominating the rolling one.

Only the since-last-dose-change index feeds the titration interval rule; reaching 4 on that index is what stretches the wait from 28 days to 42. This is why the two indices are reported separately on every prescription read, and why escalating a rung resets one to zero while frequently leaving the other untouched.

### 3.9. Subscription Billing: Cycles, Pricing, Settlement and Reversal

A `BillingAdmin` starts the recurring programme subscription for a prescription, naming the `patient_id`, the `prescription_id` the subscription bills for, an `anchor_at` instant that opens billing cycle 1, and an optional `coaching_addon_enabled` boolean that defaults to false. The subscription opens in `ACTIVE` status with `paused_at` null, `pause_days_used` at zero, `cycle_count` at 1, and all five coaching credit counters at zero unless the add-on was purchased. Creation simultaneously opens the first billing cycle: `sequence_number` 1, `period_start_at` equal to `anchor_at`, `period_end_at` exactly 30 days later, status `OPEN`. When `coaching_addon_enabled` is true, opening that cycle also grants 4 coaching credits, raising `coaching_credits_granted` and `coaching_credits_available` to 4.

Every cycle spans exactly 30 days and every later cycle abuts its predecessor exactly, so the `period_end_at` of one cycle is the `period_start_at` of the next with no gap and no overlap. The window is half-open: `period_start_at` is inclusive, `period_end_at` exclusive. Cycles are never created by a client; like titration rungs they exist only as side effects, and the cycle list is the only channel through which they are discovered. Each cycle records its `subscription_id`, its `sequence_number`, its window, a `status` of `OPEN`, `INVOICED`, `SETTLED` or `VOIDED`, and a battery of money fields that all start at zero: `medication_charge_cents`, `coaching_addon_fee_cents`, `dispensing_fee_cents`, `adherence_credit_cents`, `total_due_cents`, `settled_amount_cents`, `proration_credit_cents` and `coaching_unused_credit_cents`. Its `charge_basis`, `invoiced_at` and `void_reason` all start null.

**Invoicing** prices the cycle. It moves the cycle `OPEN → INVOICED`, requires the subscription to be `ACTIVE` (a paused or cancelled subscription is refused with `ERR_SUBSCRIPTION_NOT_ACTIVE`, 409), and requires the clock to be at or after the cycle's `period_start_at` — invoicing a cycle that has not begun is rejected with `ERR_INVALID_STATE` (409). It sets `invoiced_at` to the clock and computes the drug charge and then the invoice total, in that order.

The **drug charge** starts from a list price per pen. Insurance-fork prescriptions are filled with branded product listed at 25,000 cents a pen; cash-fork prescriptions are filled with compounded product listed at 20,000 cents a pen — which fork applies is read from the prescription's `active_route_mode`, exactly the mapping the routing selector of §3.7 uses. That list price is multiplied by a dose multiplier that depends on the prescription's current `dose_level`: rungs 1 and 2 carry a multiplier of 1.00, rungs 3 and 4 carry 1.25, and rung 5 carries 1.50. The product is rounded half-up to whole cents to give the per-unit price, and **only then** is it multiplied by the prescription's `units_per_cycle` to give the gross amount. Rounding after the multiplication instead of before is a different — and wrong — number.

From that gross amount two readings are prepared, and the prescription's `active_route_mode` selects which one is used:

- The **cash reading** takes 15 percent of the gross amount, rounds it half-up to whole cents, and caps that discount at 9,000 cents; the amount due is the gross amount less the capped discount. No payer cap applies here, so the figure scales with both `dose_level` and `units_per_cycle`.
- The **insurance reading** first caps the gross amount at the plan-allowed ceiling of 42,000 cents. From that allowed amount it subtracts a flat copay of 3,500 cents, floors the difference at zero, takes 20 percent of it, and rounds that coinsurance half-up to whole cents. The amount due is the copay plus the coinsurance, capped in turn at the per-cycle out-of-pocket maximum of 9,000 cents. Because of the two caps this figure is nearly insensitive to `dose_level`.

When `active_route_mode` is `INSURANCE` the cycle's `charge_basis` is written as `INSURANCE_ADJUDICATED` and `medication_charge_cents` takes the insurance reading; otherwise `charge_basis` is written as `CASH_PAY` and `medication_charge_cents` takes the cash reading.

The **invoice total** is then assembled in six pinned steps, each reading only values fixed by earlier steps.

1. `medication_charge_cents` is the figure just computed.
2. `coaching_addon_fee_cents` is 4,900 cents when the subscription's `coaching_addon_enabled` is true at invoice time, and 0 otherwise.
3. The subtotal is `medication_charge_cents` plus `coaching_addon_fee_cents`.
4. `dispensing_fee_cents` is 0 when that subtotal is at least 36,000 cents, and 2,500 cents otherwise. The waiver test reads the subtotal *excluding* the dispensing fee, even though the fee is part of the total the member ultimately sees — this is deliberate and resolves what would otherwise be a fee waived on the strength of a total it belongs to.
5. `adherence_credit_cents` rewards engagement. Count the check-ins for the subscription's `prescription_id` whose status is `CLEARED`, `ESCALATED` or `RESOLVED` and whose `triaged_at` falls at or after the cycle's `period_start_at` and strictly before its `period_end_at`. Zero such check-ins earns nothing; one or two earns 1,500 cents; three or more earns 3,000 cents.
6. `total_due_cents` is the subtotal plus `dispensing_fee_cents` minus `adherence_credit_cents`, floored at zero so a generous credit can never produce a negative invoice.

No rounding happens anywhere in these six steps, because every input is already a whole number of cents.

**Settlement** collects. It moves the cycle `INVOICED → SETTLED` and requires the subscription to be `ACTIVE`. A `payment_reference` may optionally accompany the request. Settlement first computes `coaching_unused_credit_cents` under the completed-only reading of the coaching entitlement described in §3.10, then sets `settled_amount_cents` to `total_due_cents` less that credit, floored at zero. That settled amount is added to the member's `lifetime_charged_cents`, the forward leg of the billing conservation identity. Settlement also rolls the subscription forward: it opens the next billing cycle with `period_start_at` exactly equal to this cycle's `period_end_at` and `period_end_at` 30 days beyond that, gives it `sequence_number` equal to the subscription's `cycle_count` plus one, increments `cycle_count`, and — when `coaching_addon_enabled` is true — grants another 4 coaching credits.

**Voiding** reverses, and what it does depends entirely on where the cycle was. A void request submitted directly by a `BillingAdmin` carries a `void_reason` in its body, and the only value that endpoint accepts is `ADMIN_REVERSAL`; any other value is rejected with `ERR_VALIDATION` (400). The other two reasons, `SUBSCRIPTION_PAUSED` and `SUBSCRIPTION_CANCELLED`, are written only by the cascades described below.

- From `SETTLED`, the void adds the pre-void `settled_amount_cents` to the member's `lifetime_credited_cents` and then sets `settled_amount_cents` to zero. This is the compensating leg of the billing conservation identity: the charge is not erased, it is offset by a visible credit.
- From `INVOICED`, the void computes `proration_credit_cents` using the clock as the stop instant, and leaves both lifetime counters untouched because nothing was ever collected.
- From `OPEN`, the void leaves `proration_credit_cents` at zero, because nothing was ever invoiced, and likewise touches neither lifetime counter.

`VOIDED` is terminal.

**Proration** is computed whenever an invoiced cycle is voided, whether by the direct void or by one of the cascades. Take the whole days elapsed from the cycle's `period_start_at` to the clock — the difference in seconds divided by 86,400 with the remainder discarded — and clamp that figure to the range 0 through 30 inclusive, so a void before the window opened prorates as though no days had elapsed and a void long after it closed prorates as though all 30 had. Unused days are 30 minus the clamped elapsed days. Three of the invoice components are then prorated: `medication_charge_cents`, `coaching_addon_fee_cents` and `dispensing_fee_cents`. Each is multiplied by the unused days, divided by 30, and rounded half-up to whole cents **separately**; the three rounded results are then added together to give `proration_credit_cents`, and that sum is never rounded again. `adherence_credit_cents` does not participate at all — engagement credit is already earned and is never prorated back.

**Pausing and resuming.** A `BillingAdmin` or the member may suspend billing, moving the subscription `ACTIVE → PAUSED`. The pause is refused with `ERR_PAUSE_LIMIT_EXCEEDED` (422) when `pause_days_used` has already reached the cumulative ceiling of 60 days; a pause is admissible only while `pause_days_used` is strictly less than 60. A successful pause sets `paused_at` to the clock and fires a three-hop cascade: hop one is the status change; hop two moves the subscription's billing cycle currently in `OPEN` or `INVOICED` to `VOIDED` with `void_reason` `SUBSCRIPTION_PAUSED`, computing `proration_credit_cents` when that cycle had been invoiced; hop three moves every coaching session citing that voided cycle's `billing_cycle_id` and still in `SCHEDULED` to `FORFEITED`.

Resuming moves the subscription `PAUSED → ACTIVE`. It adds the whole days between `paused_at` and the clock to `pause_days_used`, clears `paused_at`, and opens a fresh billing cycle whose `period_start_at` is the clock and whose `period_end_at` is 30 days later, with `sequence_number` equal to `cycle_count` plus one and `cycle_count` incremented. When `coaching_addon_enabled` is true, that new cycle grants another 4 credits. A subscription may pause and resume repeatedly until the cumulative 60-day ceiling is reached.

**Cancellation** is terminal. A `BillingAdmin` or the member may cancel from either `ACTIVE` or `PAUSED`, and only the member's own subscription may be cancelled by a member. Cancelling from `ACTIVE` fires the same three-hop cascade as a pause, except that `void_reason` is written as `SUBSCRIPTION_CANCELLED`: the `OPEN` or `INVOICED` cycle is voided with `proration_credit_cents` computed when it had been invoiced, and every `SCHEDULED` coaching session on that cycle is forfeited. Cancelling from `PAUSED` fires no cascade at all — a pause has already voided the live cycle and forfeited its sessions, so nothing but the subscription's own `status` and `updated_at` changes.

### 3.10. Nutrition Coaching and the Entitlement Pool

The coaching add-on is sold as an entitlement of sessions rather than as sessions themselves. Every time a billing cycle opens while `coaching_addon_enabled` is true — at subscription creation, at settlement of the preceding cycle, and at resume — 4 credits are added to `coaching_credits_granted`. Those credits move through four other counters over their lifetime, and the sum of the four always equals the granted total, as §2.10 requires.

A member books a session by naming the `subscription_id` whose pool it draws from, the `coach_provider_id` who will deliver it, and the window: an inclusive `scheduled_start_at` and an exclusive `scheduled_end_at` that must be strictly after it. Four gates run, in this order:

1. The subscription must be `ACTIVE`; a `PAUSED` or `CANCELLED` subscription is refused with `ERR_SUBSCRIPTION_NOT_ACTIVE` (409).
2. The named practitioner must have `provider_type` `COACH` and `status` `ACTIVE`; a clinician or a suspended coach is refused with `ERR_PROVIDER_NOT_ELIGIBLE` (422).
3. The window must not collide with another `SCHEDULED` session of the same coach. Coaching uses a plain half-open overlap test with no buffer whatsoever: a collision exists when the new session's `scheduled_start_at` falls earlier than the other session's `scheduled_end_at` *and* the other session's `scheduled_start_at` falls earlier than the new session's `scheduled_end_at`. Two sessions that exactly abut — one ending at the instant the next begins — therefore do not collide, in deliberate contrast to the buffered consult rule of §3.3. A collision is refused with `ERR_COACH_SLOT_CONFLICT` (409). Then the session must be placed in a cycle: `scheduled_start_at` must fall at or after the `period_start_at` and strictly before the `period_end_at` of exactly one billing cycle of that subscription whose status is `OPEN` or `INVOICED`, and that cycle's identifier becomes the session's `billing_cycle_id`. A start instant landing in no such window is refused with `ERR_INVALID_STATE` (409).
4. The entitlement must cover it. Under the **reservation-inclusive** reading, `coaching_credits_available` equals `coaching_credits_granted` less `coaching_credits_reserved` less `coaching_credits_consumed` less `coaching_credits_forfeited`, and a booking is permitted only while that figure is at least 1. A member holding four granted credits with one session already scheduled therefore sees three available. A booking attempted with zero available is refused with `ERR_COACHING_CREDITS_EXHAUSTED` (402).

A successful booking lands the session in `SCHEDULED` with `completed_at` null and moves one credit from `coaching_credits_available` to `coaching_credits_reserved`.

The coach who owns the session marks it delivered, moving it `SCHEDULED → COMPLETED`; the acting identity must match the session's `coach_provider_id` and the subscription must still be `ACTIVE`. Completion sets `completed_at` to the clock and moves one credit from `coaching_credits_reserved` to `coaching_credits_consumed`. Either the member or the coach may instead cancel a scheduled session, moving it `SCHEDULED → CANCELLED` and moving one credit from `coaching_credits_reserved` back to `coaching_credits_available` — restoring the pre-booking split exactly. Forfeiture, driven only by the cycle-void cascades of §3.9, moves the session `SCHEDULED → FORFEITED` and moves one credit from `coaching_credits_reserved` to `coaching_credits_forfeited`; availability is not restored, which is precisely what distinguishes a forfeit from a cancellation. `COMPLETED`, `CANCELLED` and `FORFEITED` are all terminal.

At settlement the programme credits back the part of the add-on fee the member did not use, and it does so under a deliberately *different* reading of the same counters. The **completed-only** reading ignores reservations entirely: unused credits are `coaching_credits_granted` less `coaching_credits_consumed`, floored at zero. That count is multiplied by a refund rate of 1,000 cents per credit, and the result is capped at 4,900 cents — the add-on fee itself, so the credit-back can never exceed what was charged for the add-on. The result is written to the cycle's `coaching_unused_credit_cents` and subtracted from `total_due_cents` to give `settled_amount_cents`. Because this reading ignores reservations while the booking gate honours them, the same member with four granted credits, one consumed and one still scheduled is refunded for three unused credits even though one of those three is already committed to a session that has not yet been delivered. That asymmetry is intended.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — enrolling a member, registering a practitioner or a pharmacy, recording a supply lot, opening a screening, booking a consult, issuing a prescription, filing a prior authorisation, creating a pharmacy order, starting a subscription, filing a check-in, or booking a coaching session — return `201 Created`. Every other successful operation, including all state transitions, all reads and the clock control, returns `200 OK`. In the Authorized Role(s) column below, **Any** means all six declared roles: `Patient`, `Provider`, `Coach`, `PharmacyOperator`, `BillingAdmin` and `PlatformAdmin`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/glp1/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/glp1/patients` | Enrol a member | PlatformAdmin |
| GET | `/glp1/patients/{patient_id}` | Read a member, including live BMI, eligibility mirror and lifetime billing counters | Any |
| PATCH | `/glp1/patients/{patient_id}/vitals` | Record a new weight and recompute the live BMI | Patient, Provider |
| POST | `/glp1/providers` | Register a clinician or a coach | PlatformAdmin |
| POST | `/glp1/pharmacies` | Register a dispensing pharmacy | PlatformAdmin |
| POST | `/glp1/supply-lots` | Record a physical lot held by a pharmacy | PlatformAdmin |
| GET | `/glp1/supply-lots/{supply_lot_id}` | Read a lot including its three unit counters | Any |
| GET | `/glp1/supply-lots` | List lots, optionally filtered to one pharmacy | Any |
| POST | `/glp1/screenings` | Open a draft eligibility screening and snapshot the member's height | Provider, Patient |
| GET | `/glp1/screenings/{screening_id}` | Read a screening including its frozen BMI and decision reason | Any |
| GET | `/glp1/screenings` | List screenings, optionally filtered by member | Any |
| POST | `/glp1/screenings/{screening_id}/submit` | Submit or resubmit a screening for adjudication | Provider |
| POST | `/glp1/consults` | Book a telehealth consult slot with a clinician | Patient |
| GET | `/glp1/consults/{consult_id}` | Read a consult | Any |
| GET | `/glp1/consults` | List consults, optionally filtered by member or clinician | Any |
| POST | `/glp1/consults/{consult_id}/complete` | Close a consult as prescribing, declining or no-show | Provider |
| POST | `/glp1/consults/{consult_id}/reschedule` | Move a no-showed consult back to a new scheduled window | Patient, Provider |
| POST | `/glp1/prescriptions` | Issue a prescription off a prescribing consult and an eligible screening | Provider |
| GET | `/glp1/prescriptions/{prescription_id}` | Read a prescription including both status axes and both severity indices | Any |
| GET | `/glp1/prescriptions` | List prescriptions, optionally filtered by member, consult, prescriber, screening, superseded predecessor or either status axis | Any |
| POST | `/glp1/prescriptions/{prescription_id}/discontinue` | End a prescription clinically | Provider, Patient |
| POST | `/glp1/prescriptions/{prescription_id}/request-refill` | Advance the fulfilment axis from dispensed to refill-due | Patient, Provider |
| GET | `/glp1/titration-steps/{titration_step_id}` | Read a titration rung including its planning escalation date | Any |
| GET | `/glp1/titration-steps` | List titration rungs | Any |
| POST | `/glp1/titration-steps/{titration_step_id}/escalate` | Step the dose ladder up one rung | Provider |
| POST | `/glp1/titration-steps/{titration_step_id}/hold` | Freeze a rung on clinical judgement without changing the dose | Provider |
| POST | `/glp1/titration-steps/{titration_step_id}/reduce` | Step the dose ladder down one rung | Provider |
| POST | `/glp1/prior-authorizations` | File a prior authorisation with the payer | Provider |
| GET | `/glp1/prior-authorizations/{prior_authorization_id}` | Read a prior authorisation | Any |
| GET | `/glp1/prior-authorizations` | List prior authorisations, optionally filtered by prescription | Any |
| POST | `/glp1/prior-authorizations/{prior_authorization_id}/decide` | Record the payer's decision on a submitted or appealed authorisation | BillingAdmin |
| POST | `/glp1/prior-authorizations/{prior_authorization_id}/appeal` | Appeal a denial back to the payer | Provider |
| POST | `/glp1/pharmacy-orders` | Route a fill to a pharmacy and lot chosen by the routing selector | Provider |
| GET | `/glp1/pharmacy-orders/{pharmacy_order_id}` | Read a pharmacy order including its routed pharmacy, lot and product form | Any |
| GET | `/glp1/pharmacy-orders` | List pharmacy orders, optionally filtered by prescription, rung, pharmacy or lot | Any |
| POST | `/glp1/pharmacy-orders/{pharmacy_order_id}/reserve` | Hold units on the routed lot for this order's shipping window | PharmacyOperator |
| POST | `/glp1/pharmacy-orders/{pharmacy_order_id}/ship` | Ship a reserved order | PharmacyOperator |
| POST | `/glp1/pharmacy-orders/{pharmacy_order_id}/cancel` | Cancel an order that has not shipped | PharmacyOperator, Provider |
| POST | `/glp1/subscriptions` | Start the recurring programme subscription for a prescription | BillingAdmin |
| GET | `/glp1/subscriptions/{subscription_id}` | Read a subscription including all five coaching-credit counters | Any |
| GET | `/glp1/subscriptions` | List subscriptions, optionally filtered by member or prescription | Any |
| POST | `/glp1/subscriptions/{subscription_id}/pause` | Suspend billing | BillingAdmin, Patient |
| POST | `/glp1/subscriptions/{subscription_id}/resume` | Restart billing from the current clock | BillingAdmin, Patient |
| POST | `/glp1/subscriptions/{subscription_id}/cancel` | Terminate the subscription | BillingAdmin, Patient |
| GET | `/glp1/billing-cycles/{billing_cycle_id}` | Read a billing cycle including every charge component and both credit fields | Any |
| GET | `/glp1/billing-cycles` | List billing cycles | Any |
| POST | `/glp1/billing-cycles/{billing_cycle_id}/invoice` | Price the cycle | BillingAdmin |
| POST | `/glp1/billing-cycles/{billing_cycle_id}/settle` | Collect the invoiced amount and open the next cycle | BillingAdmin |
| POST | `/glp1/billing-cycles/{billing_cycle_id}/void` | Void a cycle | BillingAdmin |
| POST | `/glp1/check-ins` | File a side-effect check-in | Patient |
| GET | `/glp1/check-ins/{check_in_id}` | Read a check-in including its computed severity score | Any |
| GET | `/glp1/check-ins` | List check-ins, optionally filtered by member, prescription or triaging clinician | Any |
| POST | `/glp1/check-ins/{check_in_id}/triage` | Triage a submitted report, clearing or escalating it | Provider |
| POST | `/glp1/check-ins/{check_in_id}/resolve` | Close an escalation | Provider |
| POST | `/glp1/coaching-sessions` | Book a coaching session against the subscription's entitlement | Patient |
| GET | `/glp1/coaching-sessions/{coaching_session_id}` | Read a coaching session | Any |
| GET | `/glp1/coaching-sessions` | List coaching sessions, optionally filtered by subscription, coach or billing cycle | Any |
| POST | `/glp1/coaching-sessions/{coaching_session_id}/complete` | Mark a session delivered, burning the reserved credit | Coach |
| POST | `/glp1/coaching-sessions/{coaching_session_id}/cancel` | Cancel a scheduled session, returning the credit to the pool | Patient, Coach |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_PHARMACY_RESOURCE_NOT_FOUND` | 404 |
| `ERR_CLINICAL_RECORD_NOT_FOUND` | 404 |
| `ERR_FULFILLMENT_RECORD_NOT_FOUND` | 404 |
| `ERR_BILLING_RECORD_NOT_FOUND` | 404 |
| `ERR_STALE_PATIENT_VERSION` | 412 |
| `ERR_STALE_PRESCRIPTION_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_SCREENING_NOT_ELIGIBLE` | 409 |
| `ERR_OPEN_ESCALATED_CHECK_IN` | 409 |
| `ERR_TITRATION_INTERVAL_NOT_MET` | 409 |
| `ERR_TITRATION_MAX_DOSE_REACHED` | 422 |
| `ERR_SECOND_SIGNER_REQUIRED` | 422 |
| `ERR_SECOND_SIGNER_CONFLICT` | 403 |
| `ERR_PRIOR_AUTH_REQUIRED` | 409 |
| `ERR_APPEAL_LIMIT_REACHED` | 422 |
| `ERR_PROVIDER_NOT_ELIGIBLE` | 422 |
| `ERR_CONSULT_SLOT_CONFLICT` | 409 |
| `ERR_COACH_SLOT_CONFLICT` | 409 |
| `ERR_NO_ELIGIBLE_SUPPLY_LOT` | 409 |
| `ERR_LOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_UNITS_EXCEED_LIMIT` | 422 |
| `ERR_COACHING_CREDITS_EXHAUSTED` | 402 |
| `ERR_PAUSE_LIMIT_EXCEEDED` | 422 |
