# Pharmacy Benefit Management API — Product Requirements Document

## 1. Introduction

A Pharmacy Benefit Manager (PBM) sits between health plans, pharmacies, drug manufacturers, and members, and its job is to adjudicate every prescription claim correctly the first time: deciding what the plan allows, what the member owes, and what rebate the plan earns. This API is the adjudication and benefit-administration core of such a system. It models the configuration surface a plan administrator controls — benefit plans with their deductibles, out-of-pocket ceilings, tier copays, formulary drugs, step-therapy protocols, manufacturer copay cards, and rebate agreements — and the operational surface where pharmacy claims flow through real-time adjudication, prior-authorization review, and rebate accrual.

The system is, at heart, a ledger reconciliation engine with a compliance backbone. Each claim is a ledger row that, when paid, simultaneously moves a member's accumulators, draws down a manufacturer copay card, consumes a prior authorization, and accrues a rebate to the plan; when that claim is later reversed, every one of those effects must unwind atomically and exactly. Layered on top are the clinical gatekeeping rules of modern pharmacy benefits — step therapy that requires a member to try first-line therapies first, prior authorizations that a clinical reviewer submits but only an independent medical director may approve, specialty-pharmacy channel restrictions, refill-too-soon protection, and a rebate-clawback mechanism that lets manufacturers reclaim finalized rebates when the underlying claim is unwound. Because claims read across plan configuration, member state, and authorization state in a single inline adjudication, correctness depends on a precisely specified evaluation order and a strict segregation of duties between the roles that intake, decide, configure, and dispense.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API. All resource paths are mounted under the `/pbm` prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `PlanAdmin`, `PharmacistReviewer`, `MedicalDirector`, and `PharmacyProvider`. A `PlanAdmin` configures benefit plans, the formulary, step-therapy protocols, members, copay cards, and rebate agreements, and runs the rebate-finalization sweep. A `PharmacistReviewer` intakes prior-authorization requests and appeals denied authorizations, but is never permitted to decide an authorization. A `MedicalDirector` approves or denies prior authorizations, but may not decide one they themselves submitted. A `PharmacyProvider` submits and reverses pharmacy claims. All four roles may read any resource through the GET (list and fetch) endpoints; the write operations are partitioned exclusively as described above.

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and the server never compares it to any entity's `id`. The server does, however, record it where a workflow demands accountability: when a `PharmacistReviewer` submits a prior authorization, the submitter's `X-User-ID` is persisted on that authorization as `submitted_by_user_id`, and when a `MedicalDirector` decides an authorization, the decider's `X-User-ID` is persisted as `decided_by_user_id`. These recorded identifiers drive the segregation-of-duties check described in §3.

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

List endpoints accept two pagination query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100 rather than rejected. The `offset` parameter specifies how many items to skip from the start of the result set and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` query value that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order, ties broken by ascending `id`. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in this system — benefit plans, formulary drugs, members, prior authorizations, claims, copay cards, rebate agreements, and rebate accruals — carry a standard set of system-managed fields. Every such resource has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when it was created, an `updated_at` timestamp recording its most recent modification, and an integer `version` that begins at 1 on creation and increments by one on every mutation of the resource. The `version` field is the basis for optimistic concurrency control described in §2.6.

Step-therapy protocols are the single exception: they are lightweight reference records that are immutable after creation. A `StepTherapyProtocol` carries only an `id` and a `created_at` timestamp; it has neither an `updated_at` field nor a `version` field.

Whenever a derived field on a resource changes as a side effect of some other operation — for example, when a member's accumulators are recomputed, or when a copay card's used-benefit total changes — that counts as a mutation of the affected resource: its `updated_at` is refreshed and its `version` increments.

### 2.5. Monetary Precision and Rounding

All monetary amounts in this system are expressed and stored as integer cents; there are no fractional cents. Cost scaling by days of supply, accumulator sums, copay-card draws, and rebate accruals are all exact integer-cent computations. Two computations involve a multiplier and therefore require rounding: the mail-order copay (a tier copay multiplied by the plan's mail-order multiplier) and the rebate clawback (a finalized accrual multiplied by the agreement's clawback fraction). In both cases the result is rounded to a whole number of cents using the round-half-up method (a value with a fractional part of exactly one half rounds up to the next cent).

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each requiring the caller to declare the version of a parent resource it believes it is acting against. These are non-optional fields on those two requests; no other endpoint accepts a version field, and endpoints not listed here perform no version check.

Deciding a prior authorization requires the request body to carry `expected_prior_authorization_version`, holding the client's last observed `version` of the target authorization. If that value does not match the authorization's current `version` — for instance because the authorization was denied, appealed, and re-decided since the medical director last read it, legitimately advancing its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a decision against a stale view of the authorization.

Running the rebate-finalization sweep against a benefit plan requires the request body to carry `expected_benefit_plan_version`, holding the client's last observed `version` of the plan. If that value does not match the plan's current `version` — for instance because the plan's formulary or rebate configuration was edited since the plan administrator last read it, legitimately advancing the plan's version — the sweep is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing finalization against a stale rebate basis.

### 2.7. Resource Existence and Validation Ordering

Every operation runs its checks in a fixed priority order so that failures are reported consistently and earlier, structural problems mask later, business-specific ones. Authentication comes first: a request missing its headers fails with `ERR_UNAUTHENTICATED` before anything else. Authorization comes second: a present-but-unpermitted role fails with `ERR_FORBIDDEN`. Existence comes third: every resource referenced by a path identifier or a foreign-key body field must exist, validated left to right in the order the references are read — member, then drug, then plan, then prior authorization, then copay card — and the first missing reference yields `ERR_NOT_FOUND`. State legality comes fourth: an operation that drives a state transition requires its target to be in a state that permits the transition (a prior authorization must be in `PENDING_REVIEW` or `APPEALED` to be decided, a claim must be `PAID` to be reversed, a rebate accrual must be `PROVISIONAL` to be finalized), and a violation yields `ERR_INVALID_STATE` (HTTP 409). Only after these structural gates pass does an operation evaluate its business-specific rules, in the order each workflow describes in §3.

Across all endpoints, a request whose body is missing a required field, carries an ill-typed value, presents an out-of-range number, or supplies an enum value outside its allowed set is rejected with `ERR_INVALID_REQUEST` (HTTP 422). This is the lowest-priority validation relative to the business-specific rules of §3; it is the catch-all for malformed input that is not caught by a more specific business rule. However, this structural parsing of the request body — required-field presence, type, range, and enum-membership checks on the body fields — runs immediately after authorization and before the existence checks of the referenced foreign keys, so a request that is both malformed in its body and references a non-existent resource surfaces `ERR_INVALID_REQUEST` ahead of `ERR_NOT_FOUND`.

### 2.8. The Server Clock

Claim adjudication is time-sensitive — fill dates determine refill-too-soon overlaps and prior-authorization validity windows — so the system stamps each claim from a controllable logical server clock rather than wall-clock time. A `PlanAdmin` may set this clock to a supplied instant; until it is ever set, it reads `1970-01-01T00:00:00.000Z`. The clock-set capability accepts a single field, `to_iso8601`, the ISO 8601 UTC instant to which the clock should advance, and returns the resulting `current_utc`. Every subsequent claim stamps its `fill_date` from this clock.

## 3. Business Logic & Workflows

### 3.1. Configuring a Benefit Plan and Its Formulary

A `PlanAdmin` establishes the benefit framework by creating a **benefit plan**. A plan is created with a display `name`, a `plan_year` (the calendar year for which its accumulators apply — accumulators reset per year), an annual individual `deductible_cents`, an annual `oop_max_cents` out-of-pocket maximum, and a `tier_copay_cents` map. The deductible must be zero or greater, and the out-of-pocket maximum must be at least as large as the deductible. The `tier_copay_cents` map carries exactly four keys — `TIER_1`, `TIER_2`, `TIER_3`, and `SPECIALTY` — each mapping to a flat member copay in cents (zero or greater) charged after the deductible is met for a retail 30-day fill. Two optional configuration fields round out a plan: `mail_order_copay_multiplier`, the factor by which a single 30-day tier copay is scaled to price a 90-day mail-order fill (it must be greater than zero and defaults to 2.0, meaning a 90-day mail fill costs two copays), and `specialty_requires_specialty_pharmacy`, a boolean that defaults to true. A plan begins life with `status` of `ACTIVE` and version 1; a `PlanAdmin` may later archive it, moving its `status` to `ARCHIVED` and incrementing its version.

Onto a plan, a `PlanAdmin` lists **formulary drugs**. A formulary drug is created against a plan (the request carries the `plan_id`) with an `ndc` National Drug Code string, a `drug_name`, a `tier` that is one of `TIER_1`, `TIER_2`, `TIER_3`, or `SPECIALTY`, and an `ingredient_cost_cents` that is the plan-allowed ingredient cost in cents for a 30-day supply and must be greater than zero. Several optional flags govern adjudication: `is_specialty` (default false) marks the drug as a specialty product; `pa_required` (default false) marks the drug as requiring an approved prior authorization before any claim against it can pay; `step_therapy_protocol_id` (default null) links the drug to a step-therapy gate; and `rebate_per_fill_cents` (default 0, and zero or greater) is the manufacturer rebate the plan accrues per paid 30-day-equivalent fill. A drug begins `ACTIVE`; a `PlanAdmin` may later delist it, setting its `status` to `INACTIVE` as a soft removal.

A `PlanAdmin` also defines **step-therapy protocols**. A protocol is created against a plan (it carries the `plan_id`) with a display `name` and a non-empty `first_line_ndcs` array of NDC strings. The protocol expresses a clinical rule: before a member may fill a gated drug, they must already have tried one of these first-line therapies, as detailed in §3.4.

### 3.2. Members, Copay Cards, and Rebate Agreements

A `PlanAdmin` enrolls a **member** into a plan by supplying the member's `plan_id` and `full_name`. A new member starts `ACTIVE`, with both accumulators — `deductible_met_cents` and `oop_met_cents` — at 0. These two accumulators are computed fields: they are never written directly but are recomputed from the member's paid claims on every adjudication and every reversal, as detailed in §3.6. A member's record always reflects the live accumulator values. A `PlanAdmin` may terminate a member, moving `status` to `TERMINATED`, after which no new claims may be filed for them.

To subsidize member cost-sharing, a `PlanAdmin` issues a **copay card** to a member for a specific drug, supplying the `member_id`, the `formulary_drug_id`, and a `max_benefit_cents` lifetime benefit cap (which must be greater than zero). A card starts `ACTIVE` with `benefit_used_cents` of 0, where `benefit_used_cents` is a computed field tracking the total drawn from the card across paid claims. As described in §3.5, when a card's used benefit reaches its `max_benefit_cents` cap the card's `status` becomes `EXHAUSTED`, and a reversal that drops the used benefit back below the cap returns the card to `ACTIVE`.

On the rebate side, a `PlanAdmin` records a **rebate agreement** between the plan and a manufacturer, supplying the `plan_id`, a `manufacturer_name`, and an optional `clawback_pct`. The `clawback_pct` is the fraction of an accrued rebate the manufacturer reclaims when the underlying claim is reversed after the accrual has been finalized; it must lie between 0 and 1 inclusive and defaults to 1.0 (full clawback). The existence of a rebate agreement for a plan is what enables rebate accrual on that plan's paid claims, as detailed in §3.7.

### 3.3. Prior Authorization: Intake, Decision, Appeal

Certain drugs cannot be dispensed until a clinical reviewer and an independent medical director have signed off. A `PharmacistReviewer` opens this workflow by submitting a **prior authorization** for a member and a drug, supplying the `member_id`, the `formulary_drug_id`, the total `authorized_fills` the authorization should grant once approved (which must be at least 1), and a `valid_through_date`. The reviewer may also set `overrides_step_therapy` (default false), which, on an approved authorization, additionally satisfies any step-therapy gate on the drug. A submitted authorization is created in `PENDING_REVIEW`, with the submitter's identity recorded in `submitted_by_user_id` and `decided_by_user_id` left null. The `approved_quantity_remaining` field — the count of paid fills the authorization still authorizes — starts at 0 and is only set when the authorization is approved.

A `MedicalDirector` then decides the authorization. The decision request carries a `decision` of either `APPROVE` or `DENY`, together with the OCC field `expected_prior_authorization_version` (see §2.6). A decision is only legal while the authorization is in `PENDING_REVIEW` or `APPEALED`; otherwise it is rejected with `ERR_INVALID_STATE`. Crucially, the deciding director's `X-User-ID` must differ from the authorization's recorded `submitted_by_user_id` — a reviewer may not have their own submission approved by themselves wearing a different hat. When the deciding user equals the submitter, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. On the decide endpoint these checks evaluate in the §2.7 priority order — first the legality of the current state, then the segregation-of-duties check, then the version match — so that an authorization in an undecidable state surfaces `ERR_INVALID_STATE` before any segregation or version concern is examined, and a self-decision surfaces `ERR_SEGREGATION_OF_DUTIES` before the version is compared.

Approving an authorization moves it from `PENDING_REVIEW` to `APPROVED` (or from `APPEALED` to `APPROVED`), records the deciding director in `decided_by_user_id`, sets `approved_quantity_remaining` equal to `authorized_fills`, and increments the authorization's version. Denying an authorization moves it from `PENDING_REVIEW` to `DENIED` (or from `APPEALED` to `DENIED`), records `decided_by_user_id`, and increments the version. A denied authorization is not the end of the road: a `PharmacistReviewer` may appeal it, moving it from `DENIED` to `APPEALED`, which clears `decided_by_user_id` back to null and increments the version — looping the authorization back toward a fresh decision. An appealed authorization can then be approved or denied exactly as a pending one can, with the same segregation-of-duties and version rules applying. Finally, an `APPROVED` authorization moves automatically to `EXPIRED` — a terminal state — at the moment a paid claim consumes its last authorized fill, as described in §3.4; that automatic transition also increments the authorization's version.

### 3.4. Submitting a Claim: Gatekeeping Before Payment

A `PharmacyProvider` submits a **pharmacy claim**, which the system adjudicates inline: a single submission either succeeds and the claim becomes `PAID`, or a business rule fails and the claim is recorded as `REJECTED`. A claim is submitted with the `member_id`, the `formulary_drug_id`, the `days_supply`, and the `pharmacy_type`, plus two optional references: `prior_auth_id` (the approved authorization the claim consumes) and `copay_card_id` (a manufacturer card to apply). Every claim begins in `SUBMITTED` and its independent rebate dimension begins at `NONE`. A rejected claim is terminal and persists as an audit record (with `adjudication_status` of `REJECTED`, `supply_end_date` null, and all four computed monetary amounts left at 0); when a claim is rejected no accumulator, copay-card, prior-authorization, or rebate side effect fires. When a business rule fails, the submission's HTTP response is the corresponding error envelope (the `ERR_X` of the failed rule, at that error's HTTP status) rather than the persisted claim object; only a successful adjudication returns the `PAID` claim object, with a `201 Created` status.

Before a claim may pay, it must clear a sequence of gatekeeping checks, evaluated in the §2.7 priority order after the structural gates. First, all three referenced lifecycle resources must be live: the member must be `ACTIVE`, the drug must be `ACTIVE`, and the plan must be `ACTIVE`; a claim touching a terminated member, an inactive drug, or an archived plan is rejected with `ERR_INACTIVE_RESOURCE`. Next, the supply quantity is validated: `days_supply` must be exactly 30 or 90, and if `pharmacy_type` is `MAIL_ORDER` then `days_supply` must be 90 — any other combination is rejected with `ERR_INVALID_DAYS_SUPPLY`. The `pharmacy_type` itself is one of `RETAIL`, `MAIL_ORDER`, or `SPECIALTY`.

A specialty-channel check follows: if the drug is a specialty product and its plan has `specialty_requires_specialty_pharmacy` set to true, then the claim's `pharmacy_type` must be `SPECIALTY`, otherwise the claim is rejected with `ERR_SPECIALTY_PHARMACY_REQUIRED`. Then the prior-authorization gate: if the drug has `pa_required` set to true, the claim's `prior_auth_id` must reference an `APPROVED` authorization for the very same member and drug with `approved_quantity_remaining` of at least 1; a missing, mismatched, unapproved, or exhausted authorization is rejected with `ERR_PA_REQUIRED`. When a prior authorization is referenced, its validity window is checked: the claim's `fill_date` must fall strictly before the authorization's `valid_through_date`. The window is half-open — open at the decided instant and exclusive at the upper bound — so a fill stamped exactly at `valid_through_date` is rejected with `ERR_PA_WINDOW_EXPIRED`, as is any later fill.

The step-therapy gate is next: if the drug carries a `step_therapy_protocol_id`, the member must satisfy that protocol or the claim is rejected with `ERR_STEP_THERAPY_NOT_MET`. The member satisfies the protocol in either of two ways. The first: the claim references a prior authorization that is `APPROVED` and whose `overrides_step_therapy` flag is true — an approved override authorization satisfies the gate outright. The second, when no such overriding authorization applies: the member holds at least one `PAID` claim for a formulary drug whose `ndc` appears in the protocol's `first_line_ndcs` list. If neither condition holds, the gate is not met.

A refill-too-soon check guards against early refills: the claim's `fill_date` must not fall strictly before the `supply_end_date` of any existing `PAID` claim for the same member and the same drug. Each paid fill defines a half-open supply window running from its `fill_date` up to but not including its `supply_end_date`; a new fill whose `fill_date` lands strictly inside an existing window is an overlap and is rejected with `ERR_REFILL_TOO_SOON`, while a new fill stamped exactly at a prior window's `supply_end_date` is adjacent (not overlapping) and is allowed. Finally, if the claim carries a `copay_card_id`, that card must belong to the same member and the same drug as the claim and must be `ACTIVE`; a card that does not match the claim's member and drug, or one that is `EXHAUSTED`, is rejected with `ERR_COPAY_CARD_INVALID`.

When all of these gates pass, the claim transitions from `SUBMITTED` to `PAID` and its full set of side effects fire, as detailed in §3.5 through §3.7. As part of payment, if the claim consumed a prior authorization, that authorization's `approved_quantity_remaining` is decremented by one; should the remaining count reach zero, the authorization auto-transitions from `APPROVED` to `EXPIRED` and its version increments. At payment the claim's `fill_date` is stamped from the server clock and its `supply_end_date` is computed as the fill date advanced by the number of days of supply (30 or 90 days).

### 3.5. Pricing a Paid Claim and Drawing the Copay Card

When a claim pays, the system prices it in a fixed three-stage sequence, recording four computed amounts on the claim: `gross_cost_cents`, `member_pay_cents`, `copay_card_paid_cents`, and `plan_paid_cents`.

The gross cost comes first. The drug's `ingredient_cost_cents` is the plan-allowed cost for a 30-day supply; for a 30-day fill the `gross_cost_cents` equals that ingredient cost exactly, and for a 90-day fill it equals three times that ingredient cost.

The member's responsibility before any copay-card assistance is computed next, in three ordered phases against the member's accumulators as they stand before this claim. Begin by reading the member's remaining deductible — the plan's `deductible_cents` minus the member's current `deductible_met_cents`, floored at zero — and the member's remaining out-of-pocket room — the plan's `oop_max_cents` minus the member's current `oop_met_cents`, floored at zero. In the deductible phase, the member pays the gross cost up to the remaining deductible: the deductible portion is the smaller of the gross cost and the remaining deductible, and the post-deductible remainder is the gross cost minus that deductible portion. In the copay phase, a flat copay applies to the post-deductible remainder. The base copay is the plan's `tier_copay_cents` entry for the drug's `tier`; when the `pharmacy_type` is `MAIL_ORDER`, the copay is that base copay multiplied by the plan's `mail_order_copay_multiplier`, rounded half-up to a whole cent, and for any other pharmacy type the copay is the base copay with no multiplier. The member never pays copay on dollars still inside the deductible, so the copay portion is the smaller of that copay and the post-deductible remainder. The uncapped member responsibility is the deductible portion plus the copay portion. Finally, the out-of-pocket ceiling clamps the total: `member_pay_cents` is the smaller of the uncapped responsibility and the member's remaining out-of-pocket room.

The two pricing variants follow directly from the above: a retail or specialty 30-day fill uses the base tier copay with no multiplier, while a mail-order 90-day fill uses the base tier copay multiplied by the mail-order multiplier and rounded half-up. Both variants then pass through the same deductible, copay-cap, and out-of-pocket-clamp steps.

The copay card is drawn last. If the claim carries no `copay_card_id`, then `copay_card_paid_cents` is 0. Otherwise the card's remaining benefit is its `max_benefit_cents` minus its current `benefit_used_cents`, and `copay_card_paid_cents` is the smaller of the claim's `member_pay_cents` and that remaining benefit. Copay-card dollars pay down the member's responsibility but — importantly — do not reduce the amounts applied to the member's deductible and out-of-pocket accumulators, which track the member's true accumulator-eligible spend computed before card assistance (see §3.6). The plan's responsibility, `plan_paid_cents`, is the `gross_cost_cents` minus the `member_pay_cents`. On payment, if the claim drew on a copay card, that card's `benefit_used_cents` is recomputed; when it equals the card's `max_benefit_cents` the card's `status` becomes `EXHAUSTED`.

### 3.6. Member Accumulators: Chronological Reconciliation

A member's deductible-met and out-of-pocket-met accumulators are not simple running counters that increment per claim; they are recomputed from scratch by replaying the member's paid claims in chronological order whenever a claim pays or a claim is reversed. This replay model is what keeps the accumulators exactly correct when a mid-history claim is reversed and the deductible-eligible portions of later claims must shift.

To recompute `deductible_met_cents`, the system processes the member's `PAID` claims in `created_at` ascending order, starting the total at zero. For each claim in turn, it determines the remaining deductible at that point (the plan's `deductible_cents` minus the running total, floored at zero), takes the deductible portion as the smaller of that claim's `gross_cost_cents` and the remaining deductible, and adds that portion to the running total. The final running total is the member's `deductible_met_cents`.

To recompute `oop_met_cents`, the system again processes the member's `PAID` claims in `created_at` ascending order, starting at zero. For each claim, it computes the member's true out-of-pocket for that claim as the claim's `member_pay_cents` minus its `copay_card_paid_cents` — that is, the portion the member actually bore after card assistance — and accumulates it, clamping the running total at the plan's `oop_max_cents` at each step. The final clamped total is the member's `oop_met_cents`.

These two recomputations behave differently depending on what triggered them. When a new claim has just turned `PAID`, that claim is included in the chronological replay. When an existing `PAID` claim has just turned `REVERSED`, that claim is excluded from the set and the running sums are rebuilt without it — and because the deductible portion of each claim depends on the running total before it, excluding an early claim can shift the deductible portions of every later claim. This is precisely why the accumulators are replayed rather than adjusted by subtraction.

### 3.7. Rebate Accrual, Finalization, and Clawback

When a claim pays, and only when the drug's `rebate_per_fill_cents` is greater than zero and a rebate agreement exists for the member's plan, the system creates a **rebate accrual** crediting the plan. The accrual records the `claim_id` of the paying claim and the `rebate_agreement_id` of the crediting agreement — when the plan has more than one rebate agreement, the earliest-created one (by `created_at`, then `id`) is credited — and computes `accrued_cents` on a 30-day-equivalent basis: a 30-day fill counts as one fill and accrues the drug's `rebate_per_fill_cents` once, while a 90-day fill counts as three fills and accrues three times the per-fill rebate. A new accrual is created in `PROVISIONAL` status with `clawback_cents` of 0, and the originating claim's independent `rebate_status` dimension is set to `ACCRUED`.

A provisional accrual is an estimate that can still evaporate. A `PlanAdmin` periodically runs the rebate-finalization sweep for a plan, which moves every `PROVISIONAL` accrual whose underlying claim is still `PAID` to `FINALIZED` and increments each affected accrual's version; this sweep also requires the OCC field `expected_benefit_plan_version` to match the plan's current version (see §2.6), and it reports back a `finalized_count` and the list of `finalized_accrual_ids` (the response `data` is this `{finalized_count, finalized_accrual_ids}` summary object, not the plan). Only those provisional accruals whose underlying claim belongs to a member enrolled in this plan are finalized. Running the sweep always bumps the plan's own `version` and `updated_at`, even when no accrual is finalized. The two accrual variants differ in exactly this way: a `PROVISIONAL` accrual carries a credited estimate that is simply deleted with no clawback if its claim is reversed early, whereas a `FINALIZED` accrual is locked and a later reversal triggers a clawback instead of deletion.

The clawback is the rebate dimension's reckoning when a paid claim is reversed. Reversing a claim is a `PharmacyProvider` action permitted only while the claim is `PAID`; it moves the claim to `REVERSED` and unwinds every payment side effect. The member's `deductible_met_cents` and `oop_met_cents` are recomputed with this claim excluded (per the chronological reconciliation of §3.6). If the claim drew on a copay card, that card's `benefit_used_cents` is recomputed excluding this claim, and if the used benefit drops below the card's `max_benefit_cents` the card's `status` returns to `ACTIVE`. If the claim consumed a prior authorization that has not been expired and consumed elsewhere, the authorization's `approved_quantity_remaining` is incremented by one to restore the consumed fill. And the rebate side unwinds according to the accrual's state: if a rebate accrual exists for this claim and it is still `PROVISIONAL`, the accrual is deleted and the claim's `rebate_status` returns to `NONE`; if instead the accrual has already been `FINALIZED`, the system sets the accrual's `clawback_cents` to its `accrued_cents` multiplied by the agreement's `clawback_pct`, rounded half-up to a whole cent, moves the accrual from `FINALIZED` to `CLAWED_BACK` (incrementing its version), and sets the claim's `rebate_status` to `CLAWED_BACK`. The claim's adjudication dimension, carried in `adjudication_status` (`SUBMITTED`, `PAID`, `REVERSED`, or `REJECTED`), and its rebate dimension, carried in `rebate_status`, thus evolve independently on the same row.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions, the archive/delist/terminate operations, the clock-set capability, and the rebate-finalization sweep — return a `200 OK` status code. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pbm/plans` | Create a benefit plan | PlanAdmin |
| GET | `/pbm/plans/{id}` | Fetch a plan | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/plans` | List plans | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/plans/{id}/archive` | Archive a plan | PlanAdmin |
| POST | `/pbm/plans/{id}/finalize-rebates` | Finalize all provisional rebate accruals for paid claims under the plan | PlanAdmin |
| POST | `/pbm/formulary-drugs` | Add a drug to a plan's formulary | PlanAdmin |
| GET | `/pbm/formulary-drugs/{id}` | Fetch a formulary drug | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/formulary-drugs` | List formulary drugs | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/formulary-drugs/{id}/delist` | Delist a drug | PlanAdmin |
| POST | `/pbm/step-therapy-protocols` | Create a step-therapy protocol | PlanAdmin |
| GET | `/pbm/step-therapy-protocols/{id}` | Fetch a protocol | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/step-therapy-protocols` | List protocols | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/members` | Enroll a member in a plan | PlanAdmin |
| GET | `/pbm/members/{id}` | Fetch a member (includes live accumulators) | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/members` | List members | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/members/{id}/terminate` | Terminate a member | PlanAdmin |
| POST | `/pbm/prior-authorizations` | Submit a prior authorization request | PharmacistReviewer |
| GET | `/pbm/prior-authorizations/{id}` | Fetch a prior authorization | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/prior-authorizations` | List prior authorizations | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/prior-authorizations/{id}/decide` | Approve or deny a prior authorization | MedicalDirector |
| POST | `/pbm/prior-authorizations/{id}/appeal` | Appeal a denied prior authorization back into review | PharmacistReviewer |
| POST | `/pbm/claims` | Submit and inline-adjudicate a pharmacy claim | PharmacyProvider |
| GET | `/pbm/claims/{id}` | Fetch a claim | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/claims` | List claims | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/claims/{id}/reverse` | Reverse a paid claim and unwind its side effects | PharmacyProvider |
| POST | `/pbm/copay-cards` | Issue a manufacturer copay card to a member for a drug | PlanAdmin |
| GET | `/pbm/copay-cards/{id}` | Fetch a copay card | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/copay-cards` | List copay cards | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/rebate-agreements` | Create a manufacturer rebate agreement for a plan | PlanAdmin |
| GET | `/pbm/rebate-agreements/{id}` | Fetch a rebate agreement | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/rebate-agreements` | List rebate agreements | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/rebate-accruals/{id}` | Fetch a rebate accrual | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| GET | `/pbm/rebate-accruals` | List rebate accruals | PlanAdmin, PharmacyProvider, MedicalDirector, PharmacistReviewer |
| POST | `/pbm/_clock/set` | Set the server clock used to stamp claim fill dates and evaluate PA validity windows | PlanAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INACTIVE_RESOURCE` | 409 Conflict |
| `ERR_INVALID_DAYS_SUPPLY` | 422 Unprocessable Entity |
| `ERR_SPECIALTY_PHARMACY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PA_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STEP_THERAPY_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PA_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REFILL_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_COPAY_CARD_INVALID` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
