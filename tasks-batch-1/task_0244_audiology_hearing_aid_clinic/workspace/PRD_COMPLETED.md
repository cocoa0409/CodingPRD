# Audiology & Hearing Aid Clinic API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Audiology & Hearing Aid Clinic API, a back-office platform that carries a patient from the first hearing evaluation through device selection, a supervised fitting trial, insurance allowance reconciliation, follow-up adjustments, warranty and loss/damage claims, recurring battery and supply subscriptions, trial-period returns, and manufacturer recalls with firmware reprogramming. The clinic operates as a small accounting shop wrapped around clinical care: nearly every action a clerk or audiologist takes moves money, consumes a benefit pool, or commits the clinic to a future obligation, and every one of those movements must reconcile against a single immutable ledger.

The platform exists to keep three things honest at once — the clinical record (who was tested, what they can hear, which device is medically indicated), the money (what the patient owes after allowance and coinsurance, what is refunded on a return, what a warranty deductible costs), and the device fleet (which firmware is shipping, which units are under recall, which trials are still open). Because returns reverse purchases, appeals reopen denied claims, and recalls fan out across an entire model's installed base, the system is built around explicit state machines, conserved-quantity financial invariants, and optimistic-concurrency guards on the two writes where a stale view would silently corrupt a settlement or a recall count. The remainder of this document defines the global contract every endpoint obeys (Section 2), the business workflows and their scattered rules (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which that user is acting. If either header is missing, or if `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `ClinicAdmin`, `Audiologist`, `BillingClerk`, and `Patient`. When an authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three of the four roles are operator identities not tied to any persisted record. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any stored entity; the server does not compare it to any entity's `id`. `ClinicAdmin` owns catalog management, recall issuance and closure, supply fulfillment, and the test-driving clock. When `X-User-Role` is `Audiologist`, `X-User-ID` is likewise an opaque operator identifier; the server may persist it — for example, an evaluation records the performing clinician in its `audiologist_user_id` field and an adjustment session records the performing clinician in its own `audiologist_user_id` field — but it never compares it to any entity's `id`. When `X-User-Role` is `BillingClerk`, `X-User-ID` is again an opaque operator identifier, used for the financial operations (benefit grants, purchase, return, warranty financials, sale finalization) and never matched against an entity `id`.

The `Patient` role is different: it is entity-backed. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`, and ownership checks on any resource that references a patient compare that resource's `patient_id` to `X-User-ID`. A `Patient` acting on a resource they do not own — appealing a claim on someone else's order, pausing, resuming, or cancelling a subscription that is not theirs, or skipping a cycle under a subscription that is not theirs — is rejected with `ERR_FORBIDDEN` (HTTP 403). This ownership check is distinct from, and evaluated after, the role-permission check that also yields `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set; it defaults to 0 and may not be negative. If `limit` falls outside the inclusive range of 1 through 100, or if `offset` is negative, the request is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422).

Unless a specific endpoint states otherwise, every list endpoint returns its results sorted by `created_at` in ascending order. The patient ledger listing follows the same chronological ordering — entries are returned oldest first by `created_at`, which is the order in which ledger reconciliation replays them.

Beyond `limit` and `offset`, list endpoints accept a fixed set of optional exact-match filter query parameters; an absent or empty filter parameter is simply not applied, and an unrecognized filter parameter is silently ignored rather than rejected. The supported filters are: `status` for `GET /clinic/patients`; `status` and `min_severity` for `GET /clinic/device-models`; `patient_id` and `status` for `GET /clinic/allowance-benefits`; `status` for `GET /clinic/patients/{id}/evaluations`; `status` for `GET /clinic/patients/{id}/orders`; `evaluation_id`, `device_model_id`, `allowance_benefit_id`, and `status` for `GET /clinic/orders`; `reason` and `status` for `GET /clinic/orders/{id}/adjustments`; `claim_type` and `status` for `GET /clinic/orders/{id}/warranty-claims`; `status` for `GET /clinic/patients/{id}/subscriptions`; `fitting_order_id`, `patient_id`, and `status` for `GET /clinic/subscriptions`; `status` for `GET /clinic/subscriptions/{id}/cycles`; `device_model_id`, `status`, and `severity_level` for `GET /clinic/recalls`; `status` for `GET /clinic/recalls/{id}/adjustments`; and `source_kind` for `GET /clinic/patients/{id}/ledger`. These filters are applied as exact equality against the named field; they do not themselves trigger `ERR_INVALID_REQUEST` or `ERR_VALIDATION_LIMIT` for unknown values, which simply match nothing.

Separately from pagination bounds, every write endpoint validates the shape of its request body against the type, enum, and range constraints declared for each field — for example `ear_count` being 1 or 2, `cadence_days` being 30, 60, or 90, and `coinsurance_pct` being at least 0 and strictly less than 1. A body that is missing a required field, carries a value of the wrong type, or violates such an enum or range constraint is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of items matching the query before pagination and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties and Resource Lifecycle

Almost every resource in the system carries a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only and is never accepted as a business-decision input. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation — including mutations that arrive as a cascaded side effect of an operation on another resource. Both `created_at` and `updated_at` are stamped from the server's logical clock (Section 3.11), so a test that advances the clock and then creates or mutates a resource sees the advanced instant in these fields; the envelope's `api_request_timestamp` (Section 2.2) is the lone timestamp drawn from wall-clock time rather than the logical clock. The `version` field is an integer that starts at 1 and increments by exactly 1 on every mutation; it is the basis for optimistic concurrency control.

There is one deliberate exception. The `LedgerEntry` is an append-only record and carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, because a ledger entry is never modified once written. Every other entity — `Patient`, `DeviceModel`, `AllowanceBenefit`, `HearingEvaluation`, `FittingOrder`, `AdjustmentSession`, `WarrantyClaim`, `SupplySubscription`, `SupplyCycle`, and `RecallNotice` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations mutate more than one entity. Whenever an operation writes a secondary entity as a downstream consequence — for example, superseding a previously finalized evaluation, recomputing a benefit pool's consumed amount, or rolling scheduled supply cycles into a skipped state — that secondary entity is itself mutated: its `updated_at` is refreshed and its `version` is incremented by 1, exactly as if it had been written directly. Cascades may chain (an order purchase recomputes a benefit pool, and the recomputation may in turn flip that pool's lifecycle status), and each hop is an independent mutation of the entity it touches. The specific cascade chains are described where the triggering workflow is described, in Section 3.

### 2.6. Nested Resource Retrieval and Referential Existence

Validation across the API follows a fixed precedence so that the same failing request always produces the same error. Authentication (the presence of valid headers and a known role, yielding `ERR_UNAUTHENTICATED`) is checked first; then role permission and, for a `Patient`, resource ownership (both yielding `ERR_FORBIDDEN`); then the existence of every referenced resource (yielding `ERR_NOT_FOUND`); then, for a transition endpoint, whether the requested transition is defined from the target's current state (yielding `ERR_INVALID_STATE`); and only then the endpoint's domain-specific business rules. A failure earlier in this chain masks any failure that would otherwise have surfaced later.

Many paths address a resource nested under a parent, and many request bodies reference other resources by foreign key. Existence is validated left-to-right: first the identifiers embedded in the URL path, in order from left to right, then the foreign keys carried in the request body. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404), before any deeper validation runs. For example, listing the adjustment sessions under an order whose `id` does not exist fails with `ERR_NOT_FOUND` for that order before the system considers any session.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer counts of cents; the API never represents money as a fractional number of cents. Where a calculation produces a fractional cent — coinsurance on a post-allowance remainder, a percentage-based warranty deductible, or a loyalty-discounted supply charge — the result is rounded half up to the nearest whole cent. Rounding is applied once, at the point each calculation specifies, never iteratively. Where a calculation is purely a minimum or maximum of integer cent values (as in benefit allocation), no rounding is needed because the inputs are already whole cents.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two. Fulfilling an approved warranty claim with a replacement requires the request body to carry `expected_warranty_claim_version`, a non-optional field that must equal the target claim's current `version`. If a writer has advanced the claim's `version` since the client last read it — most importantly, because the settlement is recomputed on each approval and a stale view would post a deductible that no longer reflects the current assessed amount — the replacement is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, issuing a recall notice requires the request body to carry `expected_recall_notice_version`, a non-optional field that must equal the target recall's current `version`; if the recall's `version` has advanced since the client last observed it (for instance, because the affected device model's firmware was edited in between), the issue is rejected with `ERR_STALE_VERSION` (HTTP 412), because issuing on a stale view would freeze an affected-order count that no longer matches the catalog. No other endpoint accepts or requires a version field; endpoints not named here perform no concurrency check.

### 2.9. Severity Classification and Device Indication

Hearing-loss severity is a five-band classification derived from a single pure-tone average measurement, and device indication is a ranked comparison against that classification. The bands, from least to most severe, are `NORMAL`, `MILD`, `MODERATE`, `SEVERE`, and `PROFOUND`; a device model declares the least severe band it is indicated for in its `min_severity` field, drawn from `MILD`, `MODERATE`, `SEVERE`, or `PROFOUND`. A device is indicated for a given evaluation when the evaluation's classified band is at least as severe as the model's `min_severity` band — that is, the rank of the evaluation's severity is greater than or equal to the rank of the model's `min_severity`, where the ranking runs `MILD` below `MODERATE` below `SEVERE` below `PROFOUND`. The exact numeric thresholds that produce each band are given with the evaluation workflow in Section 3.

### 2.10. The Ledger and Conserved-Quantity Invariants

The `LedgerEntry` collection is the single source of truth for every cent that moves between a patient and the clinic. Each entry records the `patient_id` whose money it moves, a `source_kind` naming the subsystem that produced it (one of `ORDER_PURCHASE`, `ORDER_RETURN`, `ALLOWANCE_APPLIED`, `WARRANTY_DEDUCTIBLE`, or `SUPPLY_BILLING`), a `source_ref_id` that points polymorphically at the order, claim, or supply cycle that produced it (resolved according to `source_kind`), a signed `amount_cents`, and an optional human-readable `memo`. The sign convention is fixed: a positive `amount_cents` is a charge to the patient and a negative `amount_cents` is a credit or refund to the patient; an applied allowance is recorded as a negative offset against the purchase charge. Ledger entries are never edited or deleted; compensating events (returns, deductibles) are expressed as new entries, never as reversals of old ones.

Two financial invariants are conserved by construction and must hold after every relevant operation. First, a purchased order returned within its trial window must leave the patient's net charge for that order equal exactly to the device model's restocking fee — the refund is computed so that the patient's bill, after folding in allowance and coinsurance, nets out to the restocking fee and nothing more. Second, a warranty settlement always splits the assessed value exactly into the patient's deductible and the clinic's absorbed cost, with no remainder: the deductible plus the clinic cost equals the assessed value. The formulas that realize these invariants live with their workflows in Section 3.

## 3. Business Logic & Workflows

### 3.1. Patients, the Device Catalog, and Benefit Pools

The clinic's reference data is established before any clinical work happens. A patient record is registered by a `ClinicAdmin` or a `BillingClerk` with a `full_name` and a `date_of_birth` (formatted `YYYY-MM-DD`); an `insurer_name` may also be supplied but is informational only and defaults to absent when omitted — it is not itself a benefit pool. A new patient begins life with a `status` of `ACTIVE`, which may later read `INACTIVE`; the `date_of_birth` is retained because it is what lets the clinic derive whether a patient is pediatric at the moment an evaluation is finalized.

The device catalog is maintained exclusively by a `ClinicAdmin`. Each device model is created with a `model_code`, a marketing `name`, a `list_price_cents` (the per-device retail price for a single ear, which must be greater than zero), a `restock_fee_cents` (the flat restocking fee charged on a trial-period return of this model, which must be at least zero), a `min_severity` band, a current shipping `firmware_version` string, and a `warranty_months` count (the manufacturer warranty length in months from purchase, which must be greater than zero). A model's `model_code` must be globally unique among all models that are not discontinued; creating a model whose `model_code` collides with an existing non-discontinued model is rejected with `ERR_DUPLICATE_MODEL_CODE` (HTTP 409). A model's `status` defaults to `ACTIVE` and may later be `DISCONTINUED`. A `ClinicAdmin` may also edit an existing model's `firmware_version`, its `list_price_cents`, or its `status` via a `PATCH`; any provided field is validated against the same constraints as at creation (price greater than zero, `status` one of `ACTIVE`/`DISCONTINUED`) and applied, while absent or `null` fields are left unchanged. Any such edit increments the model's `version` by 1; the version is bumped on every successful `PATCH` write unconditionally, including a `PATCH` that supplies none of the three editable fields (a no-op edit still refreshes `updated_at` and increments `version`). The `PATCH` does not re-check `model_code` uniqueness, since `model_code` is not editable. Editing the catalog firmware is exactly the kind of intervening write that the recall-issuance concurrency guard in Section 2.8 protects against.

Insurance allowance is modeled as a benefit pool granted to a patient by a `BillingClerk` or `ClinicAdmin`. Each pool names the owning patient via `patient_id`, carries a `plan_name` label, a `total_allowance_cents` (the total hearing-aid allowance for the benefit period, greater than zero), a `per_device_cap_cents` (the maximum allowance applicable to any single device, greater than zero), a `coinsurance_pct` (the patient's coinsurance fraction applied to the post-allowance remainder, which must be at least 0 and strictly less than 1, e.g. 0.20), and a `period_end` (formatted `YYYY-MM-DD`, the inclusive last calendar day on which the benefit may be applied). The pool also exposes a computed `consumed_allowance_cents`, which the system maintains as the sum of `allowance_applied_cents` across this patient's orders whose `status` is `PURCHASED` or `WARRANTY_ACTIVE`; it is recomputed on every order purchase, every return, and every warranty replacement. A freshly granted pool has `consumed_allowance_cents` of 0 and a `status` of `ACTIVE`, which may later read `EXHAUSTED` or `EXPIRED`.

### 3.2. The Hearing Evaluation Lifecycle

Clinical care begins with a hearing evaluation, which only an `Audiologist` may create. A new evaluation is opened against a patient by supplying the `patient_id`, the performing clinician's `audiologist_user_id`, and a `pure_tone_avg_db` — the pure-tone average threshold in the better ear, an integer in dB HL that must lie between 0 and 120 inclusive. The evaluation opens in `DRAFT` `status`; its `severity`, `is_pediatric`, and `candidate` fields are computed only at finalization and are not meaningful while the record is a draft.

Finalizing an evaluation is the act that turns a measurement into a clinical conclusion, and it is reserved to an `Audiologist`. Finalization is permitted only when the evaluation is in `DRAFT` and its `pure_tone_avg_db` has been set; otherwise the transition is rejected as an invalid state with `ERR_INVALID_STATE` (HTTP 409). On finalization the evaluation moves `DRAFT → FINALIZED`, and three derived fields are computed. The `severity` band is read off the pure-tone average using inclusive upper bounds: a value of 25 dB or below classifies as `NORMAL`; from 26 through 40 inclusive as `MILD`; from 41 through 55 inclusive as `MODERATE`; from 56 through 70 inclusive as `SEVERE`; and anything from 71 through 120 as `PROFOUND`. The boundary matters: 25 dB yields `NORMAL` while 26 dB yields `MILD`. The `candidate` flag is set true exactly when the resulting `severity` is anything other than `NORMAL`. The `is_pediatric` flag is set true exactly when the patient's age on the evaluation date — derived from the patient's `date_of_birth` and the current clock date — is under 18 years. Finalization increments the evaluation's `version` by 1.

A patient may hold at most one finalized evaluation at any time. When a new evaluation for a given patient reaches `FINALIZED`, the system automatically transitions that patient's previously finalized evaluation, if any, from `FINALIZED → SUPERSEDED`, refreshing its `updated_at` and incrementing its `version` by 1 as a cascade. `SUPERSEDED` is terminal. A fitting order that already references the now-superseded evaluation is unaffected, because the order's justification is captured as a reference at the time the order's trial begins and is not retroactively invalidated.

### 3.3. Building a Fitting Order and Starting the Trial

A fitting order is the spine of the device-fitting, warranty, and supply chain, and it is created by an `Audiologist` in `DRAFT` `status`. The creating payload supplies the `patient_id` of the patient receiving the device, the `evaluation_id` of the finalized evaluation justifying the fit, the `device_model_id` of the chosen model, and the `ear_count`, which must be 1 (monaural) or 2 (binaural). The payload may also carry an `allowance_benefit_id` naming the benefit pool to tap at purchase; when omitted the order is self-pay and `allowance_benefit_id` defaults to absent. At creation the financial fields are not yet meaningful: `trial_started_at`, `trial_deadline_at`, `gross_price_cents`, `patient_due_cents`, and `fitted_firmware_version` are absent, `allowance_applied_cents` is 0, and `refund_cents` is 0.

Starting the trial, an `Audiologist` action, advances the order `DRAFT → TRIAL` and is the gate that enforces clinical appropriateness. The transition is allowed only from `DRAFT`; an attempt from any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Several business checks then apply, and their relative order matters because each surfaces a distinct error. The referenced evaluation must belong to the same patient as the order — when the evaluation's `patient_id` does not equal the order's `patient_id`, the request is rejected with `ERR_EVALUATION_PATIENT_MISMATCH` (HTTP 422). The referenced evaluation must be `FINALIZED` and its `candidate` flag must be true; a non-candidate evaluation (one classified `NORMAL`) is rejected with `ERR_NOT_A_CANDIDATE` (HTTP 422), and an evaluation that is not in `FINALIZED` (e.g. still `DRAFT` or already `SUPERSEDED`) is rejected with the same `ERR_NOT_A_CANDIDATE` rather than with a state error — the candidacy check folds both the not-finalized and the non-candidate conditions into one failure. The chosen device model must be `ACTIVE`, and it must be medically indicated for the loss: the model's `min_severity` rank must not exceed the evaluation's `severity` rank, per the ranking in Section 2.9. A model whose `min_severity` is more severe than the patient's measured loss, or a model whose `status` is not `ACTIVE` (e.g. `DISCONTINUED`), is rejected with `ERR_DEVICE_NOT_INDICATED` (HTTP 422) — the same error covers both the not-active and the not-indicated cases. These three business-safety conditions are evaluated after the patient-mismatch check: first the patient match (`ERR_EVALUATION_PATIENT_MISMATCH`), then candidacy (`ERR_NOT_A_CANDIDATE`), then device indication (`ERR_DEVICE_NOT_INDICATED`). When the gate passes, the system stamps `trial_started_at` with the current clock instant and computes `trial_deadline_at` as `trial_started_at` plus the trial period — a fixed window of 30 days — which is the inclusive cutoff for a no-penalty return decision. Starting the trial increments the order's `version` by 1.

A `DRAFT` order that was never trialed may be abandoned: an `Audiologist` may cancel it, moving it `DRAFT → CANCELLED` (an invalid state for cancellation yields `ERR_INVALID_STATE`). `CANCELLED` is terminal, and the cancellation increments the order's `version` by 1.

### 3.4. Purchase: Allowance Waterfall, Coinsurance, and the Purchase Ledger

Converting a trial into a sale is a `BillingClerk` operation that advances the order `TRIAL → PURCHASED`, and it is where the bulk of the clinic's accounting happens. Purchase is permitted only from `TRIAL` (otherwise `ERR_INVALID_STATE`), and only while the trial window is still open: if the current clock instant is later than `trial_deadline_at`, the purchase is rejected with `ERR_TRIAL_EXPIRED` (HTTP 422). When the order names a benefit pool, two further conditions guard the benefit: the pool's `status` must be `ACTIVE` — a pool that is `EXHAUSTED` or `EXPIRED` is rejected with `ERR_BENEFIT_INACTIVE` (HTTP 422) — and the current clock date must be on or before the pool's `period_end`; a benefit applied after its period has closed is rejected with `ERR_BENEFIT_EXPIRED` (HTTP 422).

On a successful purchase the system first snapshots the price basis: `gross_price_cents` is set to the device model's `list_price_cents` multiplied by `ear_count`, and `fitted_firmware_version` is snapshotted from the device model's current `firmware_version` (this snapshot is what later recalls compare against). Allowance is then applied by a strict cap-then-pool waterfall, never pool-then-cap. If the order is self-pay (no `allowance_benefit_id`), `allowance_applied_cents` is 0. Otherwise the system first computes the per-device-eligible amount as the smaller of the order's gross price and the pool's `per_device_cap_cents`; it then computes the pool's remaining headroom as the pool's `total_allowance_cents` minus its current `consumed_allowance_cents`, floored at 0 so it never goes negative; and finally sets `allowance_applied_cents` to the smaller of the per-device-eligible amount and the remaining headroom. In the case where the gross exceeds the per-device cap and the pool still has more headroom than the cap, the applied amount equals the per-device cap (the cap binds first); in the case where the remaining headroom is smaller than the per-device-eligible amount, the applied amount equals the remaining headroom (the pool is exhausted before the cap).

The patient's net bill is then computed allowance-first, then coinsurance on the remainder. The post-allowance remainder is `gross_price_cents` minus `allowance_applied_cents`. The coinsurance amount is that remainder multiplied by the pool's `coinsurance_pct`, rounded half up to whole cents in a single rounding step; for a self-pay order the coinsurance fraction is treated as 0. The `patient_due_cents` is the post-allowance remainder plus the coinsurance amount. For a self-pay order this reduces to `patient_due_cents` equal to `gross_price_cents`, since the allowance is 0 and the coinsurance is 0.

Purchase posts to the ledger and reconciles the pool. The system appends an `ORDER_PURCHASE` ledger entry whose `amount_cents` is the positive `gross_price_cents`. When `allowance_applied_cents` is greater than 0, it also appends an `ALLOWANCE_APPLIED` ledger entry whose `amount_cents` is the negative of `allowance_applied_cents` (a credit offset); when no allowance was applied, no such entry is written. It then recomputes the pool's `consumed_allowance_cents` and, in the same pool write, if the recomputed `consumed_allowance_cents` is greater than or equal to the pool's `total_allowance_cents`, transitions the pool to `EXHAUSTED`; this recompute-and-flip is applied as a single mutation of the pool that refreshes its `updated_at` and increments its `version` by exactly 1 (not by two), regardless of whether the status flips. Purchase increments the order's `version` by 1.

### 3.5. Returns, Refunds, and Allowance Release

A return is the compensating action that unwinds a trial or a purchase, and it is a `BillingClerk` operation. An order may be returned from `TRIAL` (it was never purchased) or from `PURCHASED`; a return from any other state is rejected with `ERR_INVALID_STATE`. For a return out of `PURCHASED`, the trial window must still be open: if the current clock instant is later than `trial_deadline_at`, the late return is rejected with `ERR_RETURN_WINDOW_CLOSED` (HTTP 422), because once the trial window closes the sale is final. A return out of `TRIAL` carries no such window check.

The refund is computed by branch. When the order is returned out of `TRIAL` — that is, it was never purchased and the patient has paid nothing yet — `refund_cents` is set to the negative of the device model's `restock_fee_cents`; the negative refund expresses that the patient still owes the restocking fee even though no purchase occurred, and because no allowance was ever consumed none is released. When the order is returned out of `PURCHASED` within the open window, `refund_cents` is set to `patient_due_cents` minus the device model's `restock_fee_cents`; this is exactly the amount that leaves the patient's net charge for the order equal to the restocking fee, honoring the conserved-quantity invariant of Section 2.10 for self-pay and allowance/coinsurance orders alike, since `patient_due_cents` already folds allowance and coinsurance into the patient's bill. (A purchased return after the window would compute a refund of 0, but in practice the window check rejects it first.)

Every return appends an `ORDER_RETURN` ledger entry whose `amount_cents` is the negative of `refund_cents`. For a return out of `PURCHASED`, the order's allowance is released: the system recomputes the benefit pool's `consumed_allowance_cents` excluding this now-returned order (the recompute excludes returned orders because it sums `allowance_applied_cents` only across the patient's orders still in `PURCHASED` or `WARRANTY_ACTIVE`) and, in the same pool write, if the pool had been `EXHAUSTED` and the recomputed `consumed_allowance_cents` is now strictly less than `total_allowance_cents`, reactivates the pool to `ACTIVE`; this recompute-and-flip is applied as a single mutation that refreshes the pool's `updated_at` and increments its `version` by exactly 1 (not by two), and the recompute runs (touching the pool) whenever the returned order names a benefit pool, even if neither the consumed total nor the status ends up changing. A return out of `TRIAL` releases no allowance because none was consumed. Both branches move the order to `RETURNED`, a terminal state, and increment the order's `version` by 1.

### 3.6. Finalizing the Sale into Warranty

Once the trial window has closed on a purchased order, a `BillingClerk` finalizes the sale by activating warranty coverage, advancing the order `PURCHASED → WARRANTY_ACTIVE`. This is permitted only from `PURCHASED` (otherwise `ERR_INVALID_STATE`) and only after the trial window has closed: if the current clock instant is at or before `trial_deadline_at`, the activation is rejected with `ERR_TRIAL_NOT_CLOSED` (HTTP 422), because the sale cannot be made final while a no-penalty return is still possible. Activation increments the order's `version` by 1. Once an order is `WARRANTY_ACTIVE` it can no longer be returned; the device is now eligible for adjustments, warranty claims, and supply subscriptions.

### 3.7. Adjustments and Recall Reprogramming

An adjustment session records a visit in which a device's settings or firmware are changed, and it is recorded by an `Audiologist` against a warranty-active order. Each session names the `fitting_order_id` of the device being serviced, the performing clinician's `audiologist_user_id`, and a `reason` — one of `COMFORT`, `RECALL_REPROGRAM`, or `GAIN_TUNE`. A session may carry an `applied_firmware_version` (the firmware flashed during the visit, defaulting to absent) and, when it is a recall reprogramming, a `recall_notice_id` naming the recall it remediates (also defaulting to absent); when a `recall_notice_id` is supplied its existence is validated as a body foreign key (yielding `ERR_NOT_FOUND` before the order-state check). The order the session is recorded against must be in `WARRANTY_ACTIVE`; recording a session against an order in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409), checked after the path and body foreign keys resolve. A session is created in `COMPLETED` `status` and may later read `VOIDED`.

When the reason is `RECALL_REPROGRAM`, the firmware that is flashed must match the recall's prescribed target: the session's `applied_firmware_version` must equal the referenced recall notice's `target_firmware_version`. A mismatch is rejected with `ERR_FIRMWARE_MISMATCH` (HTTP 422); the same `ERR_FIRMWARE_MISMATCH` is raised when a `RECALL_REPROGRAM` session omits `recall_notice_id` entirely (there is no recall against which to match the firmware). This rule is what ties a remediation visit to a specific recall, and it is the condition a recall closure later checks across the whole affected fleet.

### 3.8. Warranty Claims, Settlement, and Replacement

A warranty claim is opened against a warranty-active order, and either a `BillingClerk` or the owning `Patient` may submit it. The submitting payload carries the `claim_type` (one of `DEFECT`, `LOSS`, or `DAMAGE`), the `incident_date` (formatted `YYYY-MM-DD`, the day the defect, loss, or damage occurred), and the clerk's `assessed_value_cents` (the replacement device value, which must be greater than zero). Submission validates only the structural shape of these fields (`claim_type` enum, `incident_date` as a well-formed `YYYY-MM-DD` value, and `assessed_value_cents` greater than zero); it does not at submission time enforce that the incident is on or before the clock date or that it falls within the warranty window, and the order on which the claim is opened must be in `WARRANTY_ACTIVE` (a submission against an order in any other state is rejected with `ERR_INVALID_STATE`, HTTP 409). The on-or-before-clock-date and within-warranty-window conditions are instead checked at approval. The claim opens in `SUBMITTED` `status`; its computed `deductible_cents` and `clinic_cost_cents` remain absent until the claim is approved.

A claim follows a branching lifecycle with a revert. A `BillingClerk` may approve a `SUBMITTED` claim, moving it `SUBMITTED → APPROVED`, or deny it, moving it `SUBMITTED → DENIED`. The owning `Patient` may appeal a denied claim, moving it `DENIED → APPEALED`. From `APPEALED`, a `BillingClerk` may again approve it (`APPEALED → APPROVED`) or deny it again (`APPEALED → DENIED`) — so a claim can cycle `DENIED → APPEALED → APPROVED` or `DENIED → APPEALED → DENIED`. Each of these transitions is allowed only from its stated source state and is otherwise rejected with `ERR_INVALID_STATE`; each increments the claim's `version` by 1.

Approval — whether from `SUBMITTED → APPROVED` or from `APPEALED → APPROVED` — requires the underlying order to still be `WARRANTY_ACTIVE` and requires the incident to fall within the warranty window: the clock date must be on or before the order's purchase date plus the device model's `warranty_months` months. The order's purchase date is taken from the calendar date of the order's `ORDER_PURCHASE` ledger entry's `created_at` (the canonical instant at which the purchase posted), and the window end is that date plus `warranty_months` months with the day clamped to the last valid day of the resulting month; the comparison is made against the clock date at approval, not against the claim's `incident_date`. An approval whose underlying order is no longer `WARRANTY_ACTIVE`, or whose clock date is beyond that window, is rejected with `ERR_OUTSIDE_WARRANTY_WINDOW` (HTTP 422) — the same error covers both the order-no-longer-warranty-active case and the window-exceeded case, and it is raised after the claim's own state check (`ERR_INVALID_STATE` if the claim is not `SUBMITTED` or `APPEALED`). On either approval path the settlement is computed identically and freshly, which is why the version advances and the optimistic-concurrency guard on replacement matters. The settlement splits the `assessed_value_cents` between the patient's `deductible_cents` and the clinic's `clinic_cost_cents` by claim type. For a `DEFECT`, the patient's deductible is 0 and the clinic absorbs the full assessed value as `clinic_cost_cents`. For a `DAMAGE`, the deductible is the assessed value multiplied by 25 percent, rounded half up to whole cents and then capped at 40000 cents (the cap is applied after rounding), with `clinic_cost_cents` equal to the assessed value minus that deductible. For a `LOSS`, the deductible is the assessed value multiplied by 50 percent, rounded half up to whole cents and then capped at the same 40000 cents, with `clinic_cost_cents` again equal to the assessed value minus the deductible. In every case the deductible plus the clinic cost equals the assessed value exactly.

Fulfilling an approved claim with a replacement device is the terminal step, performed by a `BillingClerk`, advancing the claim `APPROVED → REPLACED`. This write is guarded by optimistic concurrency: the request must carry `expected_warranty_claim_version` equal to the claim's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in Section 2.8; it is allowed only from `APPROVED` (otherwise `ERR_INVALID_STATE`). On replacement the system appends a `WARRANTY_DEDUCTIBLE` ledger entry whose `amount_cents` is the positive `deductible_cents`. When the `claim_type` is `LOSS`, the replacement ships with current firmware, so the order's `fitted_firmware_version` is refreshed to the device model's current `firmware_version`, and that refresh is a cascade mutation of the order that refreshes its `updated_at` and increments the order's `version` by 1; for `DEFECT` and `DAMAGE` claims the fitted firmware is left unchanged and the order is not touched (its `version` is unaffected). Replacement increments the claim's `version` by 1. `REPLACED` is terminal.

### 3.9. Supply Subscriptions and Billing Cycles

A supply subscription feeds batteries and consumables to a fitted device, and it may be created by a `BillingClerk` or by the owning `Patient`. The creating payload names the subscriber's `patient_id`, the `fitting_order_id` of the device being supplied (which must be `PURCHASED` or `WARRANTY_ACTIVE`; a subscription named on an order in any other state is rejected with `ERR_INVALID_STATE`, HTTP 409, checked after the path-and-body foreign keys resolve), the `cadence_days` between shipment cycles (one of 30, 60, or 90), and the `unit_price_cents` charged per cycle before any loyalty discount (greater than zero). On creation the system stamps `started_at` with the current clock instant, opens the subscription in `ACTIVE` `status`, and schedules its first cycle with `cycle_index` 1. The subscription also exposes a computed `cycles_fulfilled` (the count of its shipped cycles) and a computed `lifetime_billed_cents` (the sum of `billed_cents` across its shipped cycles), both starting at 0.

The owning `Patient` controls the subscription's lifecycle. An `ACTIVE` subscription may be paused (`ACTIVE → PAUSED`) and a `PAUSED` one resumed (`PAUSED → ACTIVE`), forming the cycle `ACTIVE → PAUSED → ACTIVE`; either may be cancelled (`ACTIVE → CANCELLED` or `PAUSED → CANCELLED`). Each transition is allowed only from its stated source state and otherwise yields `ERR_INVALID_STATE`, and each increments the subscription's `version` by 1. Cancellation is terminal and carries a conditional cascade: every cycle under the subscription that is still `SCHEDULED` is rolled to `SKIPPED`, while cycles already shipped or already skipped are left untouched; each cycle so rolled is itself mutated, bumping its `version`.

Each supply cycle belongs to its parent subscription via `subscription_id` and carries a 1-based monotonic `cycle_index`, a computed `due_at`, a computed `billed_cents`, and a `status` that starts at `SCHEDULED` and ends at either `SHIPPED` or `SKIPPED`. A cycle's `due_at` is the subscription's `started_at` plus its `cycle_index` multiplied by the subscription's `cadence_days` days. The next cycle for a subscription may be scheduled by a `BillingClerk` or `ClinicAdmin`; the new cycle takes the next `cycle_index` (one greater than the highest existing index for that subscription, or 1 when none exists) in `SCHEDULED` status with its `due_at` computed as above. Scheduling the next cycle is not gated on the subscription's `status`: it succeeds regardless of whether the subscription is `ACTIVE`, `PAUSED`, or `CANCELLED`, and it neither mutates the parent subscription nor bumps the subscription's `version`.

Shipping a cycle is a `ClinicAdmin` action that advances it `SCHEDULED → SHIPPED` and bills it. Shipping is allowed only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`), only while the parent subscription is `ACTIVE`, and only once the cycle is due: if the current clock instant is earlier than the cycle's `due_at`, the ship is rejected with `ERR_CYCLE_NOT_DUE` (HTTP 422). The per-cycle charge applies a loyalty discount strictly after a threshold number of cycles: the base charge is the subscription's `unit_price_cents`, and for any cycle whose `cycle_index` is greater than 6, `billed_cents` is the base multiplied by 90 percent (a 10 percent loyalty discount), rounded half up to whole cents; for any cycle whose `cycle_index` is 6 or less, `billed_cents` is the full `unit_price_cents` with no discount. The boundary is strict — the sixth cycle still bills at full price, and the discount first applies at the seventh cycle. Shipping appends a `SUPPLY_BILLING` ledger entry whose `amount_cents` is the positive `billed_cents`, then recomputes the subscription's `cycles_fulfilled` and `lifetime_billed_cents` as a cascade (bumping the subscription's `version`), and increments the cycle's `version` by 1. A scheduled cycle may instead be skipped — by a `ClinicAdmin` or the owning `Patient` — moving it `SCHEDULED → SKIPPED` and incrementing its `version` by 1; both `SHIPPED` and `SKIPPED` are terminal.

### 3.10. Recalls and Fleet Remediation

A recall notice targets a specific model and firmware combination and is managed by a `ClinicAdmin`. A draft recall is created with the `device_model_id` of the affected model, the `affected_firmware_version` being recalled, the `target_firmware_version` devices must be reprogrammed to, and a `severity_level` of either `ADVISORY` or `MANDATORY`. It opens in `DRAFT` `status`, exposes a computed `affected_order_count` (initially 0), and ends at `CLOSED`.

Issuing a recall advances it `DRAFT → ISSUED` and fans out across the installed base. The issue write is guarded by optimistic concurrency: it must carry `expected_recall_notice_version` equal to the recall's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), as Section 2.8 describes; it is permitted only from `DRAFT` (otherwise `ERR_INVALID_STATE`). On issue the system scans for fitting orders whose `device_model_id` equals the recall's `device_model_id`, whose `fitted_firmware_version` equals the recall's `affected_firmware_version`, and whose `status` is `WARRANTY_ACTIVE`, and sets `affected_order_count` to the number of matched orders. This is a direct fan-out, not a transitive cascade: the matched orders are independent of one another and each is marked by this single issue. Issuing increments the recall's `version` by 1.

Closing a recall advances it `ISSUED → CLOSED` and is permitted only from `ISSUED` (otherwise `ERR_INVALID_STATE`). For a `MANDATORY` recall, closure is gated on full remediation: every affected order must have a `COMPLETED` adjustment session whose `reason` is `RECALL_REPROGRAM` and whose `applied_firmware_version` equals the recall's `target_firmware_version`. The set of affected orders is re-derived afresh at closure time by the same match used at issue — orders whose `device_model_id` equals the recall's `device_model_id`, whose `fitted_firmware_version` equals the recall's `affected_firmware_version`, and whose `status` is `WARRANTY_ACTIVE` — rather than being read back from the frozen `affected_order_count` recorded at issue. If any affected order under a mandatory recall lacks such a session, closure is rejected with `ERR_RECALL_NOT_REMEDIATED` (HTTP 422). An `ADVISORY` recall is closed unconditionally, with no remediation check. Closing increments the recall's `version` by 1.

### 3.11. The Ledger Trail and the Test-Driving Clock

The patient ledger is read-only and returns a patient's `LedgerEntry` records in chronological order by `created_at`, optionally filtered by `source_kind`. Each entry's `source_ref_id` and `source_kind` together identify which order, claim, or supply cycle produced it, and the signed `amount_cents` lets a reader reconstruct the patient's full financial history by replaying entries oldest first. Because every money-moving operation in the workflows above appends exactly the entries it specifies — `ORDER_PURCHASE` and possibly `ALLOWANCE_APPLIED` on purchase, `ORDER_RETURN` on return, `WARRANTY_DEDUCTIBLE` on replacement, and `SUPPLY_BILLING` on a shipped cycle — the ledger is the durable record against which all balances reconcile.

All temporal logic in the system — trial deadlines, benefit period ends, warranty windows, cycle due dates — is evaluated against a server-held logical clock rather than wall-clock time. A `ClinicAdmin` may set this clock to a supplied instant by submitting a `to_iso8601` value; this test-driving capability sets the server's current UTC clock to the supplied instant and is what makes the time-dependent transitions described above deterministically testable.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and edits — return a `200 OK` status code. The clock-setting endpoint returns `200 OK` with no resource body. Every endpoint enforces the authentication, role, existence, state, and business validations described in Sections 2 and 3; the table below is a routing summary only and does not restate request bodies, response shapes, or side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clinic/patients` | Register a patient | ClinicAdmin, BillingClerk |
| GET | `/clinic/patients/{id}` | Fetch a patient | ClinicAdmin, BillingClerk, Audiologist, Patient |
| GET | `/clinic/patients` | List patients | ClinicAdmin, BillingClerk |
| POST | `/clinic/device-models` | Create a device model | ClinicAdmin |
| GET | `/clinic/device-models/{id}` | Fetch a device model | ClinicAdmin, BillingClerk, Audiologist |
| GET | `/clinic/device-models` | List device models | ClinicAdmin, BillingClerk, Audiologist |
| PATCH | `/clinic/device-models/{id}` | Edit a device model's firmware, price, or status | ClinicAdmin |
| POST | `/clinic/allowance-benefits` | Grant an allowance benefit pool | BillingClerk, ClinicAdmin |
| GET | `/clinic/allowance-benefits/{id}` | Fetch a benefit pool | BillingClerk, ClinicAdmin, Patient |
| GET | `/clinic/allowance-benefits` | List/filter benefit pools | BillingClerk, ClinicAdmin |
| POST | `/clinic/evaluations` | Create a DRAFT hearing evaluation | Audiologist |
| POST | `/clinic/evaluations/{id}/finalize` | Finalize an evaluation | Audiologist |
| GET | `/clinic/evaluations/{id}` | Fetch an evaluation | Audiologist, BillingClerk, ClinicAdmin |
| GET | `/clinic/patients/{id}/evaluations` | List a patient's evaluations | Audiologist, BillingClerk, ClinicAdmin |
| POST | `/clinic/orders` | Create a DRAFT fitting order | Audiologist |
| GET | `/clinic/orders/{id}` | Fetch a fitting order | Audiologist, BillingClerk, ClinicAdmin, Patient |
| GET | `/clinic/patients/{id}/orders` | List a patient's fitting orders | Audiologist, BillingClerk, ClinicAdmin, Patient |
| GET | `/clinic/orders` | List/filter fitting orders | Audiologist, BillingClerk, ClinicAdmin |
| POST | `/clinic/orders/{id}/start-trial` | Begin the fitting trial | Audiologist |
| POST | `/clinic/orders/{id}/purchase` | Convert trial to purchase | BillingClerk |
| POST | `/clinic/orders/{id}/return` | Return within the trial window | BillingClerk |
| POST | `/clinic/orders/{id}/activate-warranty` | Finalize the sale into warranty | BillingClerk |
| POST | `/clinic/orders/{id}/cancel` | Cancel a DRAFT order | Audiologist |
| POST | `/clinic/orders/{id}/adjustments` | Record an adjustment/reprogramming session | Audiologist |
| GET | `/clinic/orders/{id}/adjustments` | List an order's adjustment sessions | Audiologist, BillingClerk, ClinicAdmin |
| POST | `/clinic/orders/{id}/warranty-claims` | Submit a warranty claim | BillingClerk, Patient |
| GET | `/clinic/warranty-claims/{id}` | Fetch a warranty claim | BillingClerk, ClinicAdmin, Patient |
| GET | `/clinic/orders/{id}/warranty-claims` | List an order's warranty claims | BillingClerk, ClinicAdmin, Patient |
| POST | `/clinic/warranty-claims/{id}/approve` | Approve a SUBMITTED/APPEALED claim | BillingClerk |
| POST | `/clinic/warranty-claims/{id}/deny` | Deny a SUBMITTED/APPEALED claim | BillingClerk |
| POST | `/clinic/warranty-claims/{id}/appeal` | Appeal a DENIED claim | Patient |
| POST | `/clinic/warranty-claims/{id}/replace` | Fulfil an APPROVED claim with a replacement | BillingClerk |
| POST | `/clinic/subscriptions` | Create a supply subscription | BillingClerk, Patient |
| GET | `/clinic/subscriptions/{id}` | Fetch a subscription | BillingClerk, ClinicAdmin, Patient |
| GET | `/clinic/patients/{id}/subscriptions` | List a patient's subscriptions | BillingClerk, ClinicAdmin, Patient |
| GET | `/clinic/subscriptions` | List/filter subscriptions | BillingClerk, ClinicAdmin |
| POST | `/clinic/subscriptions/{id}/pause` | Pause an ACTIVE subscription | Patient |
| POST | `/clinic/subscriptions/{id}/resume` | Resume a PAUSED subscription | Patient |
| POST | `/clinic/subscriptions/{id}/cancel` | Cancel a subscription | Patient |
| POST | `/clinic/subscriptions/{id}/cycles` | Schedule the next supply cycle | BillingClerk, ClinicAdmin |
| GET | `/clinic/supply-cycles/{id}` | Fetch a supply cycle | BillingClerk, ClinicAdmin, Patient |
| GET | `/clinic/subscriptions/{id}/cycles` | List a subscription's cycles | BillingClerk, ClinicAdmin, Patient |
| POST | `/clinic/supply-cycles/{id}/ship` | Ship a due cycle | ClinicAdmin |
| POST | `/clinic/supply-cycles/{id}/skip` | Skip a scheduled cycle | ClinicAdmin, Patient |
| POST | `/clinic/recalls` | Create a DRAFT recall notice | ClinicAdmin |
| POST | `/clinic/recalls/{id}/issue` | Issue a recall | ClinicAdmin |
| POST | `/clinic/recalls/{id}/close` | Close an issued recall | ClinicAdmin |
| GET | `/clinic/recalls/{id}` | Fetch a recall notice | ClinicAdmin, Audiologist, BillingClerk |
| GET | `/clinic/recalls` | List/filter recalls | ClinicAdmin, Audiologist, BillingClerk |
| GET | `/clinic/recalls/{id}/adjustments` | List a recall's reprogramming sessions | ClinicAdmin, Audiologist, BillingClerk |
| GET | `/clinic/patients/{id}/ledger` | List a patient's ledger entries | BillingClerk, ClinicAdmin, Patient |
| POST | `/clinic/_clock/set` | Set the server's current UTC clock | ClinicAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_MODEL_CODE` | 409 |
| `ERR_EVALUATION_PATIENT_MISMATCH` | 422 |
| `ERR_NOT_A_CANDIDATE` | 422 |
| `ERR_DEVICE_NOT_INDICATED` | 422 |
| `ERR_TRIAL_EXPIRED` | 422 |
| `ERR_BENEFIT_EXPIRED` | 422 |
| `ERR_BENEFIT_INACTIVE` | 422 |
| `ERR_RETURN_WINDOW_CLOSED` | 422 |
| `ERR_TRIAL_NOT_CLOSED` | 422 |
| `ERR_OUTSIDE_WARRANTY_WINDOW` | 422 |
| `ERR_CYCLE_NOT_DUE` | 422 |
| `ERR_FIRMWARE_MISMATCH` | 422 |
| `ERR_RECALL_NOT_REMEDIATED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION_LIMIT` | 422 |
