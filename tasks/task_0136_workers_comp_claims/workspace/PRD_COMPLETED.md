# Workers-Comp Claims API — Product Requirements Document

## 1. Introduction

Workers' compensation administration sits at the intersection of three regulatory regimes that rarely agree on timing: the EDI reporting rails that carriers and state agencies use to acknowledge an injury, the wage-replacement schedules that decide how much an injured worker is paid each week, and the actuarial machinery that re-rates an employer's premium based on its loss history. This API unifies those concerns behind a single claims ledger. It governs the full arc of a claim — from the first injury report filed under the FROI/SROI EDI standard, through the determination of whether an injury is medical-only or lost-time, the calculation and disbursement of temporary and permanent disability benefits, the medical impairment rating issued at maximum medical improvement, and the light-duty return-to-work negotiation — down to the final closure and the experience-modification entry that feeds back into the employer's premium.

The system is built around a reserve ledger whose total incurred figure is a conserved quantity: every benefit payment that draws down outstanding reserve must move an equal sum into the paid column, so that an employer's true exposure is never silently inflated or deflated by routine disbursement. Layered on top of that ledger are dual-variant indemnity calculations (the same disability span yields a different number depending on whether you ask the forward-looking reserve or the chronological paid ledger, which honors a statutory waiting period the reserve ignores), strict separation-of-duties controls between the adjuster who sets money aside and the clinician who finalizes an impairment dispute, and a web of statutory time limits governing when a claim may be opened, reopened, and examined. The remainder of this document specifies the contract precisely enough that two independent implementations would behave identically on every input.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly four roles: `PlatformAdmin`, `ClaimsAdjuster`, `MedicalReviewer`, and `Employer`. A request that omits either header, or whose `X-User-Role` is not one of these four exact strings, is rejected with `ERR_UNAUTHENTICATED`. A syntactically valid request whose role is not permitted to perform the requested operation under the access matrix in Section 4 is rejected with `ERR_UNAUTHORIZED`.

Three of the four roles are opaque operator identities. When `X-User-Role` is `PlatformAdmin`, `ClaimsAdjuster`, or `MedicalReviewer`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it against any entity's `id`. The server does, however, record the acting `X-User-ID` where the separation-of-duties protocol requires it — specifically, it remembers which `ClaimsAdjuster` identifier set a claim's reserve so that the same identifier can later be barred from finalizing an impairment rating or completing an IME on that claim.

The `Employer` role is entity-backed. When `X-User-Role` is `Employer`, the `X-User-ID` is the `id` of the acting `Employer` entity; ownership checks on any resource that references an employer — directly through `employer_id`, or transitively through a claim's policy and worker — compare the relevant employer foreign key to `X-User-ID`. An employer's read access and its write operations (registering workers, opening claims, making and resolving light-duty offers) are scoped to its own resources.

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

List endpoints accept two query parameters to page through results. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be less than 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its items sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full size of the underlying collection before paging and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a uniform set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, marking creation and most-recent mutation respectively. The `version` field is an integer that begins at 1 on creation and increments by one on every mutation of the resource; it is the basis for the optimistic-concurrency protocol described in Section 2.8.

One entity departs from this convention. A wage statement is an append-only, immutable record: once filed it is never mutated, so it carries only `id` and `created_at` — it has no `updated_at` and no `version` field. Every other entity (employers, policies, workers, claims, injury reports, benefit payments, impairment ratings, return-to-work offers, reserves, IME orders, and experience-mod entries) carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

Because several rules in this system turn on the passage of time — statutory filing windows, IME appointment windows, return-to-work offer expiry — the server maintains a single logical notion of "now." An administrative test-driving capability sets this clock to a supplied instant, after which all time-gated comparisons evaluate against the new value. Setting the clock takes a `to_iso8601` field naming the instant to which the server's current UTC time should be moved.

### 2.5. Monetary Precision and Rounding

All monetary quantities in the system are integer cents; no fractional cent is ever stored or returned. Wherever a calculation produces a non-integer cent value — a division, a percentage, a rate applied to a wage — the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds away from zero to the next whole cent). The experience-modification factor `mod_factor` and the employer's `current_emr` are the sole non-cent numeric quantities; each is rounded half-up to exactly two decimal places, and the rounding is applied before any clamping to the permitted factor range.

### 2.6. The Conserved Reserve Ledger

Each claim has at most one reserve, and that reserve is the financial heart of the claim. It tracks four cumulative figures — the outstanding `indemnity_reserve_cents` still set aside for wage benefits, the outstanding `medical_reserve_cents` still set aside for medical treatment, the `indemnity_paid_cents` already disbursed in indemnity, and the `medical_paid_cents` already disbursed in medical — plus a derived `total_incurred_cents` that is the sum of those four. The total incurred figure is a conserved quantity: whenever a benefit payment moves money from the outstanding indemnity reserve into indemnity paid, the same number of cents leaves one column and enters the other, so the total incurred is unchanged by any payment-plus-drawdown pair. Outstanding reserve figures are floored at zero; a drawdown can never push them negative. This invariant must hold across every reserve mutation: creation, reserve re-projection, a benefit payment posting, a benefit payment void, and a medical payment posting.

### 2.7. Cascading State and Count Reconciliation

A single operation in this system frequently mutates more than one resource, and every secondary effect is part of the contract — not an optional convenience. The employer's `open_claim_count` is a conserved tally of that employer's claims that are not closed: it is incremented when a claim is accepted (moving out of the reported state into an active classification) and when a closed claim is reopened, and it is decremented when a claim is closed. Finalizing an impairment rating cascades into the owning claim, advancing the claim to maximum-medical-improvement. Disputing a treating-physician rating cascades the creation of a brand-new IME order. Posting an experience-mod entry cascades into the employer's stored modification factor and re-rates the modified premium on every one of that employer's policies. Each such cascade independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`.

### 2.8. Optimistic Concurrency on Claim Writes

Two write operations re-base a claim's controlling financial figures, and both are guarded by optimistic concurrency against the claim's `version`. Filing a wage statement (which fixes a new controlling weekly benefit rate and supersedes any prior statement) requires the request body to carry `expected_claim_version` holding the claim `version` the client last observed. If that value does not match the claim's current `version` — meaning another writer has advanced the claim since the client read it — the create is rejected with `ERR_STALE_CLAIM_VERSION` at HTTP 412, forcing the client to re-read before it overwrites a benefit basis it has not seen. A successful wage-statement filing itself increments the claim's `version` by one.

The same protocol guards reserve re-projection. A reserve adjustment must carry `expected_claim_version` matching the target claim's current `version`; if the claim's version has advanced since the client last read it (because another adjustment or a payment has mutated the claim), the adjustment is rejected with `ERR_STALE_CLAIM_VERSION` at HTTP 412. A successful reserve adjustment likewise increments the claim's `version` by one. These two writes are the only operations that take a version field; no other endpoint accepts or requires one.

### 2.9. Separation of Duties

Clinical and financial authority are deliberately split so that no single operator both reserves money and signs off on the determination that releases it. The system records the `ClaimsAdjuster` `X-User-ID` that created a claim's reserve. On that same claim, that recorded identifier may not be the `MedicalReviewer` who finalizes an impairment rating, and it may not be the operator who completes the IME order. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES`. This control applies specifically to impairment-rating finalization and IME completion.

### 2.10. Nested Retrieval and Referential Validation

Several read endpoints reach a child collection through its parent — a claim's injury reports, wage statements, reserves, benefit payments, impairment ratings, return-to-work offers, and IME orders are all listed under the claim, and an employer's policies, workers, and experience-mod entries are listed under the employer. For any such path, identifiers are validated left to right: the parent named first in the path must resolve before the child segment is considered, and a path whose parent does not exist is rejected with `ERR_NOT_FOUND` referencing that parent. The same left-to-right principle governs write requests: every path identifier and every foreign key in a request body must reference an existing resource, validated in order, with the first unresolved reference yielding `ERR_NOT_FOUND`.

### 2.11. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority so that the returned `error_id` is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then the separation-of-duties check on the two clinical-closure operations (`ERR_SEGREGATION_OF_DUTIES`). Existence of every referenced resource is checked next (`ERR_NOT_FOUND`), followed by the state-machine check that the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Business rules follow: EDI sequencing (`ERR_FROI_NOT_ACKNOWLEDGED`), maintenance-type-code validity (`ERR_INVALID_MTC`), the finalized-rating and acknowledged-FROI safety guard (`ERR_RATING_NOT_FINALIZED`), statutory time limits (`ERR_STATUTE_EXPIRED`), IME window conflict (`ERR_IME_WINDOW_CONFLICT`), return-to-work window conflict (`ERR_RTW_WINDOW_CONFLICT`), uniqueness (`ERR_DUPLICATE_RESOURCE`), reserve sufficiency (`ERR_RESERVE_INSUFFICIENT`), and finally field-shape validation of the request body (`ERR_INVALID_REQUEST`). Where the optimistic-concurrency check applies, a stale `expected_claim_version` surfaces as `ERR_STALE_CLAIM_VERSION` as described in Section 2.8.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Employer, Its Policies, and Its Workers

A carrier administrator stands up an employer by supplying its registered `legal_name` and the two-letter `state_code` identifying the jurisdiction whose comp law governs. A newly registered employer starts with `open_claim_count` at 0 and `current_emr` at 1.00; both are computed figures the employer never sets directly. The `current_emr` always reflects the modification factor of the most recently posted experience-mod entry for that employer (the latest by creation time wins), defaulting to 1.00 until the first such entry exists, and it is held within the band of 0.75 at the low end and 2.00 at the high end.

Against an employer, the administrator writes one or more policies. A policy names its `employer_id`, a `policy_number` that must be unique across every policy in the system, a `manual_premium_cents` figure giving the pre-experience-mod annual premium (which may not be negative), and the coverage window bounded by `effective_date` and an exclusive `expiration_date`. At creation the policy's `modified_premium_cents` is derived by multiplying `manual_premium_cents` by the owning employer's `current_emr` and rounding half-up to whole cents; this derived premium is recomputed for every policy of an employer each time a new experience-mod entry advances that employer's factor.

Workers are registered under an employer as well — by the administrator or by the employer itself. A worker carries its `employer_id`, a `full_name`, the total `gross_wages_cents` earned over a wage base window (which may not be negative), and the `weeks_worked` count over which those wages were earned (at least 1 and no more than 52). The moment a worker is created, the system computes its average weekly wage: `average_weekly_wage_cents` is the gross wages divided by the weeks worked, rounded half-up to whole cents. This figure is computed once at creation and is immutable thereafter; a later wage statement does not mutate the worker but supersedes its wage basis at the claim level.

### 3.2. Opening a Claim and the First Injury Report

A claim is opened against a `policy_id` and a `worker_id` by an adjuster or by the employer. The opener supplies the `date_of_injury` and, optionally, the `disability_days` count of calendar days the worker is or was off work. A claim begins life in `REPORTED` status with `claim_class` of `UNCLASSIFIED` and a null `denial_reason`. Claims are filterable by their policy or their worker. A statute-of-limitations guard applies at creation: a claim whose `date_of_injury` is more than the statutory filing window — 730 days, that is two years — before the current logical time may not be opened, and the attempt is rejected with `ERR_STATUTE_EXPIRED`.

Before a reported claim can advance, its injury must be reported over EDI. An adjuster drafts an injury report naming its `claim_id`, its `report_kind` (either `FROI` for a first report or `SROI` for a subsequent one), and its `maintenance_type_code`. The maintenance code must agree with the report kind: a `FROI` requires the code `00`, while a `SROI` requires one of `IP`, `CB`, `SX`, or `FN`; any other pairing is rejected with `ERR_INVALID_MTC`. A new report enters `edi_status` of `DRAFT` with a null `rejection_code`.

The EDI transmission lifecycle then proceeds through a sequence of state transitions. Transmitting moves a report from `DRAFT` to `TRANSMITTED`. For a subsequent report, transmission is gated: a `SROI` may not be transmitted unless a `FROI` for the same claim has already reached `ACKNOWLEDGED`, and an attempt to transmit a subsequent report before its first report is acknowledged is rejected with `ERR_FROI_NOT_ACKNOWLEDGED`. The carrier-side administrator then either acknowledges a transmitted report, moving it `TRANSMITTED → ACKNOWLEDGED` (a terminal state), or rejects it, moving it `TRANSMITTED → REJECTED` and recording the supplied `rejection_code`. A rejected report is not dead: the correction loop lets an adjuster re-transmit it, moving it `REJECTED → TRANSMITTED` (again subject to the FROI-before-SROI gate for subsequent reports), so the EDI cycle can repeat until acknowledgement lands.

### 3.3. Accepting, Denying, and the Medical-Only / Lost-Time Fork

Once a first report is acknowledged, the adjuster decides the claim's fate. Acceptance of any kind requires the claim's `FROI` to be `ACKNOWLEDGED` — this precondition is checked before the disability-span fork is evaluated, so it governs the medical-only path as well as the lost-time path, and an acceptance attempted while no `FROI` for the claim is `ACKNOWLEDGED` is rejected with `ERR_RATING_NOT_FINALIZED` regardless of which fork the disability span would have selected. Acceptance forks on the disability span. When the claim's `disability_days` is 0, acceptance moves the claim `REPORTED → MEDICAL_ONLY`, sets `claim_class` to `MEDICAL_ONLY`, and increments the employer's `open_claim_count` by one. When `disability_days` is greater than 0, acceptance moves the claim `REPORTED → LOST_TIME` and increments the employer's `open_claim_count` by one, but leaves `claim_class` at `UNCLASSIFIED`; the classification flips to `LOST_TIME` only later, when the first temporary-disability benefit payment posts. Acceptance into the lost-time path has two preconditions beyond the claim being in `REPORTED`: the claim's `FROI` must be `ACKNOWLEDGED`, and a reserve row must already exist for the claim. Attempting a lost-time acceptance without an acknowledged first report is rejected with `ERR_RATING_NOT_FINALIZED` (the same guard that protects permanent-disability payments); a lost-time acceptance attempted when the `FROI` is acknowledged but no reserve row yet exists for the claim is instead rejected with `ERR_INVALID_STATE`. The optional `disability_days` field may be re-supplied in the acceptance request body, in which case it overwrites the claim's stored `disability_days` before the fork is taken; the `disability_days` value in effect at acceptance is what drives the chronological waiting-period logic in the indemnity ledger.

Alternatively, a reported claim may be denied. Denial moves the claim `REPORTED → DENIED` (a terminal state) and records the supplied `denial_reason`. A denied claim contributes no losses to its employer's experience rating.

### 3.4. Setting and Re-Projecting the Reserve

For a lost-time claim, the adjuster sets a single reserve — at most one reserve may exist per claim, and a second attempt is rejected with `ERR_DUPLICATE_RESOURCE`. Reserve creation imposes no state-machine precondition on the target claim: the claim need only exist, and a reserve may be set whatever status the claim is currently in (in practice it is set while the claim is still `REPORTED`, since the reserve must already exist before a lost-time acceptance); `ERR_INVALID_STATE` is never raised by reserve creation. The reserve is created against a `claim_id` with a `severity_tier` (one of `MINOR`, `MODERATE`, or `SEVERE`) and the adjuster's forward-looking `projected_weeks` estimate of indemnity duration. From these the system computes two outstanding figures. The medical reserve is read straight from the severity table: a `MINOR` tier reserves 250,000 cents, a `MODERATE` tier reserves 1,500,000 cents, and a `SEVERE` tier reserves 7,500,000 cents. The indemnity reserve is the controlling weekly benefit rate multiplied by `projected_weeks` and rounded half-up to whole cents, where the controlling weekly rate is taken from the latest wage statement filed for the claim; if no wage statement exists yet, the weekly rate is treated as 0, so the indemnity reserve is purely medical until a wage statement fixes the rate. On creation, `total_incurred_cents` is set to the sum of the indemnity reserve, the medical reserve, and the (initially zero) paid columns.

The reserve may later be re-projected. A reserve adjustment supplies a fresh `projected_weeks` and `severity_tier`, along with the `expected_claim_version` that guards the write per Section 2.8, and recomputes both outstanding reserve figures by the same rules; the total incurred is recomputed and the claim's version advances. The forward-looking reserve and the chronological paid ledger are deliberately allowed to diverge: the reserve projects the full expected indemnity exposure across `projected_weeks` at the weekly rate and ignores the waiting-period reduction that the paid ledger applies, so for the same disability span the two figures differ by exactly the waiting-period amount.

### 3.5. Fixing the Benefit Rate via Wage Statement

When wages are verified, an adjuster files a wage statement against a `claim_id`, supplying the verified `average_weekly_wage_cents` (which may correct the worker's computed figure) and the `expected_claim_version` for the concurrency guard. Each new statement supersedes the prior one as the claim's controlling benefit-rate basis, and the latest by creation time always wins. Filing computes the statement's `ttd_weekly_rate_cents`, the temporary-total-disability weekly compensation rate, through a capped-then-floored calculation. The raw rate is the verified average weekly wage multiplied by the statutory replacement fraction of 0.6667, rounded half-up to whole cents. That raw rate is then capped: the cap is the state average weekly wage of 120,000 cents multiplied by the maximum-compensation percentage of 1.00 (again rounded half-up), and the rate is the smaller of the raw rate and the cap. Finally the capped value is floored at the statutory minimum of 15,000 cents — the weekly rate is the larger of the capped figure and that minimum. Two boundary variants follow from this: when the raw replacement amount reaches or exceeds the state-average-wage cap, the high earner's rate is pinned to that cap and the raw figure is discarded; when the raw replacement amount falls below the statutory floor, the rate is lifted to the floor regardless of the computed raw rate. Filing a wage statement increments the claim's version by one.

### 3.6. Disbursing Indemnity Benefits

Indemnity is paid out as benefit payments, each naming its `claim_id` and a `benefit_type` of `TTD`, `TPD`, or `PPD`. Every payment computes its `amount_cents` from the claim's controlling weekly rate — the `ttd_weekly_rate_cents` of the latest wage statement for the claim — and then draws that amount down from the reserve: `indemnity_paid_cents` rises by the amount and `indemnity_reserve_cents` falls by the same amount (floored at zero), preserving the conserved total. A payment begins with its `status` field set to `POSTED`, and the first temporary-disability payment (a `TTD` or `TPD` payment) flips the claim's `claim_class` to `LOST_TIME`. Posting a benefit payment imposes no precondition on the source claim's `status`: the claim need only exist, and the payment is accepted whatever status the claim is currently in (`REPORTED`, `DENIED`, `MEDICAL_ONLY`, `LOST_TIME`, `MMI`, `CLOSED`, or `REOPENED`). No state-machine check applies to benefit-payment posting, and `ERR_INVALID_STATE` is never raised by this operation; posting is constrained only by the reserve-sufficiency check stated next and, for permanent-partial payments, by the finalized-rating guard described later in this section. A payment may not draw down more indemnity than is outstanding: if the computed `amount_cents` would exceed the claim's `indemnity_reserve_cents`, the payment is rejected with `ERR_RESERVE_INSUFFICIENT`.

The amount itself depends on the benefit type. For a temporary-total payment, the daily rate is the controlling weekly rate divided by 7, rounded half-up. The compensable-day count then turns on the claim's `disability_days` against two statutory thresholds — a 7-day waiting period and a 14-day retroactive threshold. When the disability span is 7 days or fewer, nothing is compensable and the amount is 0. When the span is more than 7 days but fewer than 14, only the days beyond the waiting period count, so the compensable days are the disability days minus 7. When the span reaches 14 days or more, the waiting period is paid retroactively and every disability day is compensable. The amount is the daily rate multiplied by the compensable days, rounded half-up.

For a temporary-partial payment, the `light_duty_weekly_cents` field is required (it is ignored for the other types) and gives the worker's light-duty weekly earnings. The weekly wage loss is the claim worker's average weekly wage minus those light-duty earnings; if that loss is zero or negative, the amount is 0. Otherwise the amount is the wage loss multiplied by the partial replacement fraction of 0.6667 and rounded half-up, but capped so it never exceeds the controlling temporary-total weekly rate.

For a permanent-partial payment, the `impairment_rating_id` field is required and must reference a finalized rating; a permanent-partial payment that references a rating not in `FINALIZED` status is rejected with `ERR_RATING_NOT_FINALIZED`. The award covers a number of weeks equal to the rating's `finalized_pct` multiplied by 3.0 weeks per percentage point, and the amount is that week count multiplied by the controlling weekly rate, rounded half-up.

A posted payment may be voided. Voiding requires the payment to be in `POSTED` status — an attempt to void a payment already in `VOIDED` status is rejected with `ERR_INVALID_STATE` (this state guard governs the void action only; it does not contradict the rule above that the posting action itself never raises `ERR_INVALID_STATE`). Voiding moves the payment to `VOIDED` and performs a compensating reversal: `indemnity_paid_cents` falls by the original amount and `indemnity_reserve_cents` rises by the same amount, restoring the reserve and leaving the conserved total unchanged. Benefit payments are filterable by their claim and by the impairment rating that backs a permanent-partial award.

### 3.7. Medical Payments Against the Reserve

Separate from indemnity, medical disbursements are posted directly against the reserve. A medical payment supplies an `amount_cents` and draws down the medical side: `medical_paid_cents` rises by that amount and `medical_reserve_cents` falls by the same amount (floored at zero). As with indemnity, the total incurred is recomputed and the conserved invariant holds — money moves between the outstanding-medical and paid-medical columns without changing the total. A medical payment is not a separately persisted resource; posting one mutates the reserve in place and the endpoint responds with HTTP `201 Created` whose `data` is the updated reserve object (carrying the refreshed `medical_paid_cents`, `medical_reserve_cents`, `total_incurred_cents`, and the reserve's incremented `version`).

### 3.8. Maximum Medical Improvement and the Impairment Dispute

When a lost-time worker reaches maximum medical improvement, a medical reviewer records an impairment rating against the `claim_id`, supplying the `whole_body_pct` (a whole-person impairment percentage from 0 through 100) and the `rater_role` indicating whether a `TREATING` physician or an `IME` examiner issued it. A new rating enters `PROPOSED` status with a null `finalized_pct`.

The path to finalization depends on who rated. An `IME`-issued rating needs no dispute round: from `PROPOSED` a reviewer finalizes it directly, moving it `PROPOSED → FINALIZED`, setting `finalized_pct` to the rating's `whole_body_pct`, and cascading the owning claim to `MMI`. A `TREATING`-physician rating may instead be disputed by the adjuster while it is `PROPOSED`, which moves it `PROPOSED → DISPUTED` and cascades the creation of a fresh IME order for the same claim — that order is scheduled to begin at the current logical time and end one day later, with `examiner_name` set to `PENDING_ASSIGNMENT`, so it is immediately completable. A dispute attempt against a rating that is not both `PROPOSED` and `TREATING`-issued — whether because its status is not `PROPOSED` or because its `rater_role` is `IME` — is rejected with `ERR_INVALID_STATE`. A disputed rating can be finalized (moving it `DISPUTED → FINALIZED`, setting `finalized_pct` to `whole_body_pct`, and cascading the claim to `MMI`) only once an IME order for that claim has reached `COMPLETED`. Finalizing a lost-time claim's controlling rating is what carries the claim into the `MMI` state; the rating being finalized must belong to the claim and be in either `PROPOSED` or `DISPUTED` status. Both finalization and IME completion are subject to the separation-of-duties bar of Section 2.9.

### 3.9. Independent Medical Examinations

An IME order is scheduled against a `claim_id` with an appointment window bounded by `scheduled_start` and an exclusive `scheduled_end`, plus the `examiner_name`. A new order enters `SCHEDULED` status. The window may not overlap another non-terminal IME order for the same claim; overlap is judged on half-open intervals where touching endpoints do not count as overlapping, and a conflicting window is rejected with `ERR_IME_WINDOW_CONFLICT`. From the scheduled state, three outcomes are possible. A reviewer completes the exam — permitted only once the current logical time has reached or passed `scheduled_start` — moving it `SCHEDULED → COMPLETED`. A reviewer marks a no-show — permitted only once the current logical time has reached or passed `scheduled_end` — moving it `SCHEDULED → NO_SHOW`. An adjuster cancels the exam, moving it `SCHEDULED → CANCELLED`. Completion is the outcome that unblocks finalizing a disputed rating, and it is subject to the separation-of-duties bar.

### 3.10. The Return-to-Work Offer

The insured employer drives light-duty negotiation. Against a lost-time claim, the employer makes a return-to-work offer naming the `claim_id`, the offered `light_duty_weekly_cents` wage, and the light-duty window bounded by `start_date` and an exclusive `end_date`. A new offer enters `OFFERED` status. Its window may not overlap an already-accepted offer for the same claim, and a required buffer gap of 7 days must separate consecutive light-duty assignments — an offer that begins within 7 days of a prior accepted offer's end is treated as overlapping and is rejected with `ERR_RTW_WINDOW_CONFLICT`.

From `OFFERED`, three resolutions exist. The employer accepts the offer, moving it `OFFERED → ACCEPTED`; acceptance is permitted only while the offer's claim is in `LOST_TIME` and only if the current logical time is before the offer's `start_date`, so acceptance always precedes the light-duty start. Accepting the offer records its `light_duty_weekly_cents` as the negotiated light-duty wage, but it does not by itself become the offset for any temporary-partial payment: the temporary-partial wage-offset is always taken from the `light_duty_weekly_cents` carried in the temporary-partial benefit-payment request body (Section 3.6), never read back from any accepted offer, so the two values are independent and a temporary-partial payment may be posted whether or not a return-to-work offer exists or has been accepted. The employer may instead decline the offer, moving it `OFFERED → DECLINED`. Finally, an offer left unanswered expires by the passage of time: once the logical clock reaches or passes the offer's `start_date` while it is still `OFFERED`, the offer transitions `OFFERED → EXPIRED`.

### 3.11. Closing, Reopening, and the Revision Loop

A claim is closed once its work is done. A medical-only claim may be closed directly, moving it `MEDICAL_ONLY → CLOSED`, provided no IME order for the claim is still `SCHEDULED`. A lost-time claim must first reach maximum medical improvement; from `MMI` it may be closed, moving it `MMI → CLOSED`, provided the claim's `indemnity_reserve_cents` has been fully drawn down to 0 and no IME order for the claim remains `SCHEDULED`. Closing a claim is terminal for that cycle: it decrements the employer's `open_claim_count` by one, and on the lost-time path it also writes off any remaining `medical_reserve_cents` to zero.

A closed claim is not necessarily final. Within the statutory reopening window — the current logical time must be before the `date_of_injury` plus the reopening limit of 1,825 days, that is five years — an adjuster may reopen it, moving it `CLOSED → REOPENED` and incrementing the employer's `open_claim_count` by one to conserve the count that closing decremented. An attempt to reopen past that window is rejected with `ERR_STATUTE_EXPIRED`. A reopened claim re-enters the lost-time pipeline: from `REOPENED` an adjuster accepts it back into `LOST_TIME` (this requires a reserve row to exist for the claim), without re-incrementing the open count, which was already restored on reopen.

### 3.12. Experience Rating and Premium Re-Calculation

Periodically the carrier administrator posts an experience-mod entry that re-rates an employer's premium from its actual loss history. The entry names the `employer_id` and the `rating_year` (at most one entry may exist per employer per rating year; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`), along with the NCCI credibility `weighting_factor` (between 0 and 1 inclusive), the `ballast_cents` stabilizing value (which may not be negative), the `expected_primary_cents` (at least 1), and the `expected_excess_cents` (which may not be negative).

The modification factor is computed by comparing the employer's actual losses against expected. Actual losses are summed across every one of the employer's claims that is not denied, reading each claim's reserve total incurred; denied claims contribute nothing. Each claim's contribution is split into a primary portion and an excess portion at a per-claim split point of 1,700,000 cents: the actual primary losses are the sum over the employer's claims of the smaller of each claim's total incurred and the split point, and the actual excess losses are the sum over the employer's claims of the amount by which each claim's total incurred exceeds the split point (never less than zero). With the weighting factor as W, the numerator is the actual primary losses, plus W times the actual excess losses, plus one-minus-W times the expected excess losses, plus the ballast. The denominator is the expected primary losses, plus W times the expected excess losses, plus one-minus-W times the expected excess losses, plus the ballast. The raw modification factor is the numerator divided by the denominator; the stored `mod_factor` is that raw factor rounded half-up to two decimal places and then clamped to lie between 0.75 and 2.00. A factor above 1.00 means actual losses exceeded expected and the employer pays a surcharge (modified premium above manual); a factor below 1.00 means losses ran under expected and the employer earns a credit (modified premium below manual).

Posting the entry cascades: the employer's `current_emr` is set to the new `mod_factor`, and the `modified_premium_cents` is recomputed on every one of that employer's policies as the manual premium times the new factor, rounded half-up to whole cents.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions and the test-driving clock — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employers` | Register an employer | PlatformAdmin |
| GET | `/employers/{id}` | Fetch an employer | PlatformAdmin, ClaimsAdjuster, MedicalReviewer, Employer |
| GET | `/employers/{id}/policies` | List an employer's policies | PlatformAdmin, ClaimsAdjuster, Employer |
| GET | `/employers/{id}/workers` | List an employer's workers | PlatformAdmin, ClaimsAdjuster, Employer |
| GET | `/employers/{id}/experience-mods` | List an employer's experience-mod entries | PlatformAdmin, ClaimsAdjuster, Employer |
| POST | `/policies` | Create a workers-comp policy | PlatformAdmin |
| GET | `/policies/{id}` | Fetch a policy | PlatformAdmin, ClaimsAdjuster, Employer |
| POST | `/workers` | Register a worker; computes AWW | PlatformAdmin, Employer |
| GET | `/workers/{id}` | Fetch a worker | PlatformAdmin, ClaimsAdjuster, MedicalReviewer, Employer |
| POST | `/claims` | Open a claim | ClaimsAdjuster, Employer |
| GET | `/claims/{id}` | Fetch a claim | PlatformAdmin, ClaimsAdjuster, MedicalReviewer, Employer |
| GET | `/claims` | List claims, filterable by policy and worker | PlatformAdmin, ClaimsAdjuster, MedicalReviewer, Employer |
| POST | `/claims/{id}/accept` | Accept a claim into medical-only or lost-time | ClaimsAdjuster |
| POST | `/claims/{id}/deny` | Deny a reported claim | ClaimsAdjuster |
| POST | `/claims/{id}/close` | Close a medical-only or MMI claim | ClaimsAdjuster |
| POST | `/claims/{id}/reopen` | Reopen a closed claim within the window | ClaimsAdjuster |
| POST | `/claims/{id}/reserve-adjustments` | Re-project the claim's reserve (OCC-guarded) | ClaimsAdjuster |
| POST | `/injury-reports` | Create a FROI or SROI EDI report | ClaimsAdjuster |
| GET | `/injury-reports/{id}` | Fetch an injury report | PlatformAdmin, ClaimsAdjuster, MedicalReviewer |
| GET | `/claims/{id}/injury-reports` | List a claim's injury reports | PlatformAdmin, ClaimsAdjuster, MedicalReviewer |
| POST | `/injury-reports/{id}/transmit` | Transmit a draft or rejected report | ClaimsAdjuster |
| POST | `/injury-reports/{id}/ack` | Acknowledge a transmitted report | PlatformAdmin |
| POST | `/injury-reports/{id}/reject` | Reject a transmitted report | PlatformAdmin |
| POST | `/wage-statements` | File a wage statement (OCC-guarded) | ClaimsAdjuster |
| GET | `/claims/{id}/wage-statements` | List a claim's wage statements | PlatformAdmin, ClaimsAdjuster |
| POST | `/reserves` | Set the claim's reserve | ClaimsAdjuster |
| GET | `/reserves/{id}` | Fetch a reserve | PlatformAdmin, ClaimsAdjuster |
| GET | `/claims/{id}/reserves` | List the claim's reserve | PlatformAdmin, ClaimsAdjuster |
| POST | `/reserves/{id}/medical-payments` | Post a medical payment against the reserve | ClaimsAdjuster |
| POST | `/benefit-payments` | Post a TTD/TPD/PPD indemnity payment | ClaimsAdjuster |
| GET | `/benefit-payments/{id}` | Fetch a benefit payment | PlatformAdmin, ClaimsAdjuster |
| GET | `/claims/{id}/benefit-payments` | List a claim's benefit payments | PlatformAdmin, ClaimsAdjuster |
| GET | `/benefit-payments` | List benefit payments, filterable by claim and rating | PlatformAdmin, ClaimsAdjuster |
| POST | `/benefit-payments/{id}/void` | Void a posted benefit payment | ClaimsAdjuster |
| POST | `/impairment-ratings` | Record an MMI impairment rating | MedicalReviewer |
| GET | `/impairment-ratings/{id}` | Fetch an impairment rating | PlatformAdmin, ClaimsAdjuster, MedicalReviewer |
| GET | `/claims/{id}/impairment-ratings` | List a claim's impairment ratings | PlatformAdmin, ClaimsAdjuster, MedicalReviewer |
| POST | `/impairment-ratings/{id}/dispute` | Dispute a proposed treating-physician rating | ClaimsAdjuster |
| POST | `/impairment-ratings/{id}/finalize` | Finalize a rating; cascades claim to MMI | MedicalReviewer |
| POST | `/rtw-offers` | Create a light-duty return-to-work offer | Employer |
| GET | `/rtw-offers/{id}` | Fetch a return-to-work offer | PlatformAdmin, ClaimsAdjuster, Employer |
| GET | `/claims/{id}/rtw-offers` | List a claim's RTW offers | PlatformAdmin, ClaimsAdjuster, Employer |
| POST | `/rtw-offers/{id}/accept` | Accept an offered light-duty offer | Employer |
| POST | `/rtw-offers/{id}/decline` | Decline an offered light-duty offer | Employer |
| POST | `/ime-orders` | Schedule an Independent Medical Examination | ClaimsAdjuster |
| GET | `/ime-orders/{id}` | Fetch an IME order | PlatformAdmin, ClaimsAdjuster, MedicalReviewer |
| GET | `/claims/{id}/ime-orders` | List a claim's IME orders | PlatformAdmin, ClaimsAdjuster, MedicalReviewer |
| POST | `/ime-orders/{id}/complete` | Complete a scheduled IME | MedicalReviewer |
| POST | `/ime-orders/{id}/no-show` | Mark a scheduled IME as a no-show | MedicalReviewer |
| POST | `/ime-orders/{id}/cancel` | Cancel a scheduled IME | ClaimsAdjuster |
| POST | `/experience-mods` | Post an experience-rating entry; re-rates policies | PlatformAdmin |
| GET | `/experience-mods/{id}` | Fetch an experience-mod entry | PlatformAdmin, Employer |
| POST | `/_clock/set_current_utc` | Set the server's current UTC time (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FROI_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_INVALID_MTC` | 422 Unprocessable Entity |
| `ERR_RATING_NOT_FINALIZED` | 409 Conflict |
| `ERR_STATUTE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_IME_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_RTW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_RESERVE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_CLAIM_VERSION` | 412 Precondition Failed |
