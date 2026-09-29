# Aegis CNP Fraud Prevention API — Product Requirements Document

## 1. Introduction

Card-not-present commerce forces every merchant into the same uncomfortable trade: decline too little and the chargeback bill grows, decline too much and the best customers walk away insulted. Aegis is the fraud-operations platform that makes that trade explicit, measurable and auditable. It scores every checkout against device, behavioural, velocity, identity, address and promotion signals, blends a deterministic rule component with a calibrated model probability, and lands the result in one of three commercial bands — approve, review, or decline — using thresholds that a policy engineer publishes as a versioned artefact rather than as code.

Around that scoring core sit the operational surfaces the fraud team actually lives in. A manual-review queue that is staffed by skill and capacity rather than by whoever grabs a case first. Account-takeover detection at login and at every sensitive profile change, with step-up challenges and a containment path that locks an account and clears its in-flight reviews in a single stroke. Address intelligence that folds unit and suite variants into one canonical cluster so that a reshipper cannot hide behind "Apt 4B". A chargeback pipeline that closes the loop: a lost dispute on a fraud reason code reverses the customer's approved-value ledger, permanently disqualifies the account from good-customer standing, re-prices every open review case that account owns, and feeds the reason-code-segmented training corpus that the next model version is trained on.

Two design commitments run through the whole specification and should be read as non-negotiable. First, **every number is reproducible**: rounding steps, comparison inclusivity, evaluation order and tie-breaks are pinned, because a fraud decision that cannot be reproduced cannot be defended to an issuer or to a regulator. Second, **every consequential write is guarded**: the operator who drafts a rule pack may not activate it, the analyst who requests a policy exception may not decide it, the analyst who escalates a case may not receive it back, and the two write paths whose safety depends on a value the client read a moment earlier require that value to be presented and matched. Time itself is a server-owned quantity — a logical clock — so that velocity windows, challenge expiries and policy windows are exercisable and deterministic.

## 2. Global Specifications & System-Wide Principles

Everything in this section applies to the whole surface, which is mounted under `/fraud` apart from the clock harness described in §2.4. Where §2 and §3 describe the same rule from different angles, they reinforce rather than contradict; where §2 fixes a format or an ordering, that fixing is a contract.

### 2.1. User and Role-Based Access Control

Every request — without exception, including reads — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. A request with a missing or empty `X-User-Role` is rejected with `ERR_MISSING_ROLE`. A request whose `X-User-Role` is not one of the five recognised role names is rejected with `ERR_INVALID_ROLE`. A syntactically valid role that is simply not permitted on the addressed operation is rejected with `ERR_UNAUTHORIZED`.

The five roles are `CheckoutService`, `RiskAnalyst`, `ReviewLead`, `PolicyEngineer` and `PlatformAdmin`, spelled exactly so.

Two of those roles are entity-backed and three are opaque, and the distinction determines whether `X-User-ID` is resolved against stored data:

- When `X-User-Role` is `RiskAnalyst`, `X-User-ID` is the `id` of the acting `Analyst` row; ownership checks on any resource that references an `Analyst` compare the resource's analyst-valued field to `X-User-ID` — specifically a review case's `assigned_analyst_id` for case ownership and a policy exception's `requested_by_analyst_id` for segregation of duties.
- When `X-User-Role` is `ReviewLead`, `X-User-ID` is likewise the `id` of the acting `Analyst` row, and is compared against a policy exception's `requested_by_analyst_id` and, when re-staffing an escalated case, against that case's `escalated_by_analyst_id`.
- For both entity-backed roles, a request that omits `X-User-ID`, or supplies a value that no `Analyst` row carries as its `id`, is rejected with `ERR_INVALID_USER_CONTEXT`. This check runs on every endpoint those two roles are authorised for.
- When `X-User-Role` is `CheckoutService`, `X-User-ID` is an opaque service token not tied to any persisted entity; the server never compares it to any entity's `id`.
- When `X-User-Role` is `PolicyEngineer`, `X-User-ID` is an opaque engineer token not tied to any persisted entity. The server records it — as `created_by_user_id` when a rule pack is drafted and as `activated_by_user_id` when one is activated — and compares those two recorded values against each other, but it never resolves either against an entity row.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque administrator token not tied to any persisted entity; it is neither recorded on nor compared against any entity's `id`.

Role responsibilities, in brief. `CheckoutService` is the storefront integration: it alone opens and scores checkout assessments and records authentication events and their challenge outcomes. `RiskAnalyst` works the queue and alone requests policy exceptions, but may never staff the queue or decide an exception. `ReviewLead` alone staffs the queue (both by name and automatically) and alone decides policy exceptions, but may never request one. `PolicyEngineer` alone owns rule packs, their rules and the scoring models. `PlatformAdmin` alone owns the analyst roster and shift states, customer posture, the dispute pipeline and the logical clock, and is explicitly barred from opening or scoring assessments — decisioning belongs to the checkout service. Read access is broad but not universal; §4 is authoritative per operation.

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

### 2.3. Pagination and List Filtering

Collection reads are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100. `offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION`. Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current window).

Unless a specific collection says otherwise, list results are ordered by `created_at` ascending. Two collections override that default because their consumers need a working order rather than a chronological one: the review queue is returned in `priority_score` descending and then `created_at` ascending, and a rule pack's rules are returned in `evaluation_order` ascending and then `created_at` ascending — the same order the scoring walk uses.

List endpoints also accept exact-match filters, each named after the field it narrows. Customers filter on `tier`, `account_status`, `ato_posture` and `good_customer_flag`. Analysts filter on `status` and `seniority`. Devices filter on `reputation` and `emulator_flag`. Addresses filter on `canonical_parent_address_id` (to walk one cluster's variant rows), `canonical_address_id` (to fetch a whole cluster), `classification` and `drop_risk_state`. Rule packs filter on `status` and `blend_mode`; a pack's rules filter on `signal_family`; risk models filter on `status`. Checkout assessments filter on `customer_id`, `device_profile_id`, `shipping_address_id`, `billing_address_id`, `rule_pack_id`, `risk_model_id`, `applied_exception_id`, `state`, `decision` and `outcome_label`. Review cases filter on `assessment_id`, `assigned_analyst_id`, `escalated_by_analyst_id`, `state` and `primary_signal_family`. Authentication events filter on `customer_id`, `device_profile_id`, `event_type`, `outcome` and `challenge_state`. Chargebacks filter on `assessment_id`, `reason_code`, `state` and `guarantee_state`. Policy exceptions filter on `customer_id`, `requested_by_analyst_id`, `approved_by_analyst_id`, `whitelisted_address_id`, `scope` and `state`. The performance report takes one selector, `cohort`, described in §3.9.

### 2.4. The Logical Clock

Time is a server-owned value, not a reading of the host's wall clock. Before any client touches it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time. Every `created_at`, every `decided_at`, `resolved_at`, `assigned_at`, `activated_at`, `retired_at`, `promoted_at` and `challenge_expires_at`, and every velocity, SLA and policy-window comparison in this specification is evaluated against that clock.

`POST /_clock/set_current_utc` advances it. The request carries a single field, `current_utc`; a value that is not a valid ISO 8601 UTC instant is rejected with `ERR_VALIDATION`. The clock is monotonic: a `current_utc` earlier than the clock's present reading is rejected with `ERR_CLOCK_NOT_MONOTONIC`. Advancing the clock writes no entity — it is purely a time move, which is precisely what makes it the lever for pushing a sibling assessment out of a velocity window or letting a step-up challenge lapse.

### 2.5. Record Identity, Audit Stamps and Versioning

Resources carry a common set of server-managed properties:

- **`id`** — a server-minted UUID, with no type prefix of any kind.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at the instant the row was created.
- **`updated_at`** — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row.
- **`version`** — an integer that is 1 on creation and increments by exactly 1 on every mutation of that row, including mutations the server performs as a cascade rather than at the client's direct request.

Every entity in this system carries all four **except `FraudRule`**, which is immutable once written: a fraud rule has only `id` and `created_at`, and both `updated_at` and `version` are absent from it entirely. There is no endpoint that mutates a fraud rule.

Two consequences are worth stating plainly, because they are where implementations usually drift. A recomputation of a derived field is a mutation: when a chargeback loss re-prices a review case's `priority_score`, that case's `updated_at` and `version` both move even though no client named that case. And a cascade that touches four rows moves four `version` counters, not one.

### 2.6. Score Arithmetic, Money and Rounding Discipline

All monetary amounts in this domain are integers of minor units — cents — and are never expressed as decimals. Order totals, disputed amounts, exception ceilings, guarantee figures and the customer's approved-value ledger are all integer cents.

Scores and rates are decimals with pinned precision. Unless a rule explicitly says otherwise, rounding is **round half up**. `model_points`, `blended_score`, `ato_score`, `priority_score` and `reshipper_confidence` are carried at two decimal places; `model_raw_probability` is accepted at four decimal places; the rates in the performance report are carried at four decimal places. Where a formula nests one rounding step inside another, the nesting order is part of the contract and collapsing the steps is a defect: §3.4 pins the one case where this matters. Where a formula caps a value, the cap is applied after rounding unless stated otherwise, and the caps themselves are fixed — a rule component never exceeds 100, a blended score never exceeds 200.00, an account-takeover score never exceeds 100.00, a reshipper confidence never exceeds 1.00.

One deliberate exception to round-half-up: the guarantee programme fee is **floored**, never rounded up, so the merchant is never charged a fraction of a cent it did not owe. Band comparisons use the stored two-decimal `blended_score` exactly as stored, with no re-derivation and no tolerance.

### 2.7. Version Pinning of Decisioning Assets

A checkout assessment must be reproducible months later, when the rule pack that judged it has long been retired and three model versions have shipped since. Aegis achieves that by **pinning** both decisioning assets at the moment the assessment is opened rather than at the moment it is scored: the assessment permanently records `rule_pack_id` (the rule pack whose `status` is `ACTIVE` and whose effective window contains the current instant) and `risk_model_id` (the risk model whose `status` is `ACTIVE`). Neither field is a client input; both are computed by the server, and neither is ever rewritten.

Pinning creates a window in which the world can move underneath an unscored assessment, and the specification treats that as a hard failure rather than a silent re-pin. If either pinned asset has left `ACTIVE` by the time scoring is requested, scoring is refused — `ERR_RULE_PACK_NOT_ACTIVE` when the pack has moved on, `ERR_RISK_MODEL_NOT_ACTIVE` when the model has. The assessment stays in `PENDING_SIGNALS` forever; there is no repair path.

Symmetrically, an assessment cannot be opened at all when there is nothing to pin: the absence of an `ACTIVE` rule pack covering the current instant yields `ERR_NO_ACTIVE_RULE_PACK`, and the absence of an `ACTIVE` risk model yields `ERR_NO_ACTIVE_RISK_MODEL`. Those two are checked in that order, so a system with neither reports the missing rule pack.

### 2.8. Stale-Read Protection on Queue Staffing and Exception Decisions

Two write paths depend on a value the client read a moment earlier, and both therefore require the client to present the `version` it last observed on the **parent** row. These are the only two endpoints in the system that take a version field; every other endpoint takes none, and supplying one elsewhere has no effect.

`POST /fraud/review-cases/{id}/assign` requires `expected_analyst_version` as a non-optional field of the request body, carrying the client's last observed `version` of the `Analyst` named by `analyst_id`. If it does not equal that analyst's current `version`, the assignment is rejected with `ERR_STALE_ANALYST_VERSION` (HTTP 412). This is the guard against acting on a stale reading of the analyst's capacity: an earlier assignment may already have consumed the headroom the client believed was free, and because that earlier assignment was itself perfectly legal, no state precondition would catch the second one — the case is still `QUEUED`, the analyst is still `AVAILABLE` and still under capacity. Only the advanced `version` distinguishes the stale request from a fresh one.

`POST /fraud/policy-exceptions/{id}/decision` requires `expected_customer_version` as a non-optional field of the request body, carrying the client's last observed `version` of the beneficiary `Customer`. If it does not equal that customer's current `version`, the decision is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412). The value being protected here is the customer's policy surface — the `tier`, the `account_status`, and the set of already-`APPROVED` exceptions this decision would stack on top of. A decision on a second `REQUESTED` exception for the same customer is legitimate on its own merits, so again no state precondition rejects it; only the stale version does.

Note the asymmetry with automatic staffing, which is intentional: automatic assignment takes no version field at all, because the server chooses the analyst itself and therefore reads it fresh.

### 2.9. Cascade Discipline and the Two Conserved Ledgers

Many operations in this domain mutate more than one aggregate. The cascades are specified, not incidental, and a request either performs all of a cascade's links or none of them.

Derived counters come in two flavours, and confusing them is the most common source of drift. **Counter-style** quantities move by explicit increments and decrements: a customer's `approved_count` and `declined_count`, an analyst's `open_case_count` and `resolved_case_count`, a rule pack's `rule_count`, a model's `scored_assessment_count`, an exception's `consumed_count`, a case's `requeue_count` and `escalation_count`, a challenge's `challenge_attempts`. **Recount-style** quantities are recomputed from scratch as counts over the underlying rows every time their trigger fires: all of a device profile's derived signals and all of an address cluster's derived signals. Because a recount is a count and not an increment, running it twice with the same underlying rows leaves the value unchanged — which is why a second lost chargeback against the same order does not double-count anything.

Two quantities are treated as **conserved ledgers**, and both must hold after every single request:

- **The net approved-value ledger.** A customer's `lifetime_net_approved_cents` must always equal the sum of `amount_cents` over that customer's assessments that are in state `DECIDED_APPROVE` and whose `outcome_label` is not `FRAUD`. The compensating movements are: add the order's `amount_cents` when an assessment reaches `DECIDED_APPROVE`, whether it got there straight from `PENDING_SIGNALS` or through manual review from `IN_REVIEW`; and subtract the **assessment's** `amount_cents` when a lost dispute flips that assessment's `outcome_label` from `UNKNOWN` to `FRAUD`. The subtraction always uses the order amount, never the disputed amount, which may be partial. It also fires **only** on that `UNKNOWN` to `FRAUD` transition: a second lost dispute on an order already labelled `FRAUD` moves neither this ledger nor `confirmed_fraud_count`. Without that guard the ledger drifts negative.
- **The review-capacity ledger.** An analyst's `open_case_count` must always equal the number of review cases whose `assigned_analyst_id` is that analyst and whose `state` is `ASSIGNED`. It rises by one when a case becomes `ASSIGNED`, falls by one when an assigned case is resolved either way, falls by one when an assigned case is escalated (because the assignment is cleared), and is set to zero outright by the shift-release cascade that requeues every case the analyst was holding. A full cycle of assign, escalate, reassign and resolve must return the analyst to the count they started at, with no drift.

### 2.10. Address Cluster Canonicalisation

Addresses are stored as a single-level cluster. A row that is its own cluster root has a null `canonical_parent_address_id`, and its computed `canonical_address_id` equals its own `id`. A row that is a unit or suite variant of another address carries that other address's `id` in `canonical_parent_address_id`, and its `canonical_address_id` equals that parent's `id`. `canonical_address_id` is always server-computed and never a client input.

Clusters are strictly one level deep. Naming a parent that itself has a non-null `canonical_parent_address_id` is rejected with `ERR_ADDRESS_CLUSTER_DEPTH`.

All cluster intelligence lives on the root and only on the root. `distinct_customer_count`, `approved_use_count`, `fraud_confirmed_count`, `promo_redemption_count`, `drop_risk_state` and `reshipper_confidence` are maintained on the root, aggregating the behaviour of every row in the cluster; a variant row permanently reports 0 for its four counters, `CLEAN` for `drop_risk_state` and 0.00 for `reshipper_confidence`. Whenever this specification says an assessment "resolves to a cluster", it means: take the shipping address row, follow its `canonical_address_id`, and read or write the root.

### 2.11. Segregation of Duties

Three high-consequence decisions may not be made by the party that set them up, and each violation has its own code:

- A rule pack may not be activated by the principal whose `X-User-ID` was recorded as its `created_by_user_id`. Violation: `ERR_ACTIVATION_SEGREGATION_VIOLATION`.
- A policy exception may not be approved or rejected by the analyst recorded as its `requested_by_analyst_id`. Violation: `ERR_DECISION_SEGREGATION_VIOLATION`. Revocation is deliberately exempt — a requester may revoke their own exception.
- An escalated review case may not be re-assigned to the analyst recorded as its `escalated_by_analyst_id`. Violation: `ERR_ESCALATION_SEGREGATION_VIOLATION`.

### 2.12. Rejection Precedence

Validation is a single ordered ladder, not a set of independent checks. The **first** violated rule decides the response, and no later rule is evaluated. Bands are evaluated in this order:

1. **Authentication and authorisation** — missing role, unrecognised role, role not permitted on this operation, then the entity-backed user-context check (§2.1).
2. **Existence** — the row addressed by the path `id`, then foreign keys named in the request body, then a parent rule pack named in the path, then a fraud rule addressed directly.
3. **Request shape** — required fields present and non-null, then JSON types and enum membership (an unrecognised `action` value is an enum violation), then the fixed-format string checks, then numeric range checks, then the skill-family array check, then list pagination bounds, then clock-format.
4. **State** — whether the addressed row's current state permits the requested transition at all.
5. **Optimistic concurrency** — the two stale-parent-version checks of §2.8.
6. **Segregation of duties** — the three checks of §2.11.
7. **Cross-entity referential and eligibility rules** — analyst seniority, skill coverage and availability; pinned-asset status; case ownership; exception scope coherence; cluster depth; dispute eligibility.
8. **Temporal rules** — window ordering, dispute timing, training cutoff, clock monotonicity.
9. **Capacity and uniqueness constraints** — window collisions, analyst capacity, empty selector pool, empty rule pack, duplicate device hash, duplicate rule code, exhausted challenge attempts, underfilled training segments.
10. **Fiscal rules** — weight normalisation, band ordering, tier caps and tier eligibility, disputed-amount ceiling.

Two collisions are worth spelling out because they are easy to get backwards. On the exception-request path, the customer-not-active check (band 4) **outranks** the tier-cap check (band 10): a request that both names a locked customer and asks for more than the tier cap reports `ERR_CUSTOMER_ACCOUNT_LOCKED`, not `ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP`. On the explicit-assignment path, the escalated-requires-lead check (band 7) **outranks** the analyst-capacity check (band 9): assigning an escalated case to a non-lead analyst who is also at capacity reports `ERR_ESCALATED_REQUIRES_LEAD`, not `ERR_ANALYST_CAPACITY_EXCEEDED`. The per-operation orderings that follow from this ladder are restated where they matter in §3.

### 2.13. Path Resolution for Pack-Scoped Resources

Most resources in this domain are addressed at their own top-level collection, and cross-references travel in request bodies rather than in URL segments. The one composition expressed in the URL is the rule pack and its rules. For any path that carries more than one identifier, or that carries a parent identifier before doing anything else, identifiers are resolved strictly left to right and the first one that names nothing decides the response. A request for the rules of a rule pack that does not exist reports `ERR_RULE_PACK_NOT_FOUND` before any rule, filter or body field is considered — and that holds equally for adding a rule to the pack, listing the pack's rules, and reading the pack's performance report. Reading a fraud rule by its own identifier, outside the pack path, reports `ERR_RULE_NOT_FOUND` when no such rule exists.

Foreign keys arriving in a request body are resolved in the order the body's fields are documented, and each resolves to the target entity's own not-found code — for example, an assessment naming a valid customer but an unknown device reports `ERR_DEVICE_NOT_FOUND`. The twelve not-found codes are `ERR_CUSTOMER_NOT_FOUND`, `ERR_ANALYST_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ADDRESS_NOT_FOUND`, `ERR_RULE_PACK_NOT_FOUND`, `ERR_RULE_NOT_FOUND`, `ERR_RISK_MODEL_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_AUTH_EVENT_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND` and `ERR_EXCEPTION_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Shopper Accounts, Devices and Address Intelligence

**Shopper accounts.** A customer record is registered by either the checkout service or a platform administrator with an `email` (free-form; deliberately not uniqueness-constrained, because one household may hold several accounts and that is itself a signal) and a `home_country`, an ISO-3166 alpha-2 code that must be exactly two uppercase letters. A `tier` may be supplied and defaults to `STANDARD`; the accepted values are `STANDARD`, `HIGH_VALUE` and `BUSINESS`, and the tier gates both policy-exception eligibility and review priority. A new account starts with `account_status` `ACTIVE`, `ato_posture` `CLEAR`, `locked_reason` null, `good_customer_flag` false, and every derived counter — `lifetime_net_approved_cents`, `approved_count`, `declined_count`, `confirmed_fraud_count`, `failed_login_count` — at zero.

A customer carries **two independent posture axes on the same row**, and neither constrains the other's transition set. `account_status` moves among `ACTIVE`, `LOCKED` and `CLOSED`; `ato_posture` moves among `CLEAR`, `WATCH` and `CONTAINED`. A single cascade may move both in one request, but each axis is separately reachable and separately cleared.

A platform administrator drives either axis through the posture operation, supplying **exactly one** of `account_status` or `ato_posture` — supplying neither, or both, is `ERR_VALIDATION` — plus an optional `reason`. Four transitions are declared, and any other requested pair is rejected with `ERR_CUSTOMER_POSTURE_INVALID`; in particular nothing leaves `CLOSED`, and asking for `ato_posture` `CLEAR` on an account already `CLEAR` is not a declared transition.

- `ACTIVE → LOCKED` records the supplied `reason` into `locked_reason`, recomputes `good_customer_flag` (an account that is not `ACTIVE` is never good, so a true flag flips to false here), leaves `ato_posture` untouched, and increments the customer's `version`. This is an administrative lock only: it does **not** decline in-flight assessments. Only the containment cascade of §3.7 does that.
- `LOCKED → ACTIVE` clears `locked_reason` back to null, recomputes `good_customer_flag`, and increments `version` — making the account-status axis cyclic.
- `ACTIVE → CLOSED` sets `good_customer_flag` to false and increments `version`. `CLOSED` is terminal on both axes.
- `CONTAINED → CLEAR` sets `failed_login_count` back to zero and increments `version`. It pointedly does **not** unlock `account_status`: an account contained by the takeover cascade was also locked by it, and the administrator must clear both axes separately.

**Good-customer standing.** `good_customer_flag` is not an input. It is recomputed by the server after any write that changes `account_status`, `ato_posture`, `approved_count`, `confirmed_fraud_count` or `lifetime_net_approved_cents`, and it reads the customer row as it stands *after* that request's counter movements have landed. The flag is true only when all five of the following hold: `account_status` is `ACTIVE`; `ato_posture` is anything other than `CONTAINED`; `confirmed_fraud_count` is exactly zero; `approved_count` is at least 2; and `lifetime_net_approved_cents` is at least 20,000 cents — two hundred currency units of net approved value. Because the recomputation happens after the counters move, the approval that carries an account to its second approved order flips the flag inside that very request. And because `confirmed_fraud_count` never decreases, a single confirmed fraud disqualifies an account permanently.

**Devices.** A device fingerprint is registered by the checkout service or an administrator with a `device_hash`, which must be globally unique across device profiles — a second registration of the same hash is `ERR_DUPLICATE_DEVICE_HASH` — plus a `tz_offset_minutes` browser timezone offset in minutes and an optional `emulator_flag` that defaults to false. Reputation is derived, never supplied: it starts at `NEW`, except that a fingerprint registered with `emulator_flag` true is recomputed to `SUSPECT` in the same request, because the emulator condition is one of the reputation triggers.

A device's four derived signals are recomputed together, from scratch, whenever an assessment is scored on that device, whenever a manual review resolution touches it, and whenever a lost dispute confirms fraud on one of its orders. `distinct_customer_count` is the number of distinct customers appearing across two row sets combined: the assessments on this device whose `decision` is not null, and the authentication events on this device. `approved_use_count` is the number of assessments on this device in state `DECIDED_APPROVE`. `fraud_confirmed_count` is the number of assessments on this device whose `outcome_label` is `FRAUD`. From those, `reputation` is resolved by taking the **first** matching clause of this pinned ladder:

1. `fraud_confirmed_count` of 2 or more → `BLOCKED`.
2. `fraud_confirmed_count` of exactly 1, or `distinct_customer_count` of 3 or more, or `emulator_flag` true → `SUSPECT`.
3. `fraud_confirmed_count` of exactly 0 **and** `approved_use_count` of 3 or more **and** `distinct_customer_count` of 2 or fewer → `TRUSTED`.
4. Otherwise → `NEW`.

Because `fraud_confirmed_count` never falls, `BLOCKED` is absorbing in practice.

**Addresses.** An address is registered by the checkout service, a risk analyst or an administrator with `line1`, `postal_code` and a `country_code` of exactly two uppercase letters, plus an optional `classification` defaulting to `RESIDENTIAL` (the alternatives are `COMMERCIAL`, `FREIGHT_FORWARDER` and `PO_BOX`) and an optional `canonical_parent_address_id` linking it as a variant of an existing root, per §2.10. A fresh row starts with all four cluster counters at zero, `drop_risk_state` `CLEAN` and `reshipper_confidence` 0.00; when the new row joins an existing cluster, the cluster **root** is recomputed immediately.

Cluster intelligence is recomputed on the same three triggers as device reputation. Over every assessment whose shipping address resolves into the cluster — the root itself plus every row naming the root as its `canonical_parent_address_id` — the root's counters are recounted: `distinct_customer_count` is the number of distinct customers among those assessments whose `decision` is not null; `approved_use_count` counts those in state `DECIDED_APPROVE`; `fraud_confirmed_count` counts those whose `outcome_label` is `FRAUD`; and `promo_redemption_count` counts those that both carried a non-null `promo_code` and reached state `DECIDED_APPROVE`.

`drop_risk_state` then takes the first matching clause of its own pinned ladder:

1. `fraud_confirmed_count` of 2 or more → `KNOWN_DROP`.
2. The root's `classification` is `FREIGHT_FORWARDER` **and** `distinct_customer_count` is 3 or more → `KNOWN_DROP`.
3. `fraud_confirmed_count` of exactly 1, or `distinct_customer_count` of 3 or more, or the root's `classification` is either `FREIGHT_FORWARDER` or `PO_BOX` → `WATCH`.
4. Otherwise → `CLEAN`.

`reshipper_confidence` is a bounded sum of four contributions, rounded half up to two decimal places and capped at 1.00: 0.20 for each distinct customer up to a maximum of three counted customers; 0.15 for each promotion redemption up to a maximum of two counted redemptions; a flat 0.30 when the root's `classification` is `FREIGHT_FORWARDER`; and a flat 0.10 when the root's `classification` is `PO_BOX`. A residential root serving one distinct customer with no promotion redemptions therefore sits at 0.20.

### 3.2. Authoring Decision Policy: Rule Packs and Fraud Rules

Decision policy is authored by a `PolicyEngineer` as a **rule pack** — a versioned bundle of signal predicates plus the blending weights and band thresholds that turn their output into a decision. Drafting a pack takes a human-readable `version_label`, a `blend_mode` of either `WEIGHTED` or `RULE_DOMINANT`, the two blending weights `rule_weight` and `model_weight` (each a two-decimal number between 0.00 and 1.00 inclusive), the two band thresholds `review_floor_score` and `decline_floor_score` (two-decimal numbers; `review_floor_score` is at least 0.00 and `decline_floor_score` is at most 200.00), and the pack's decisioning window as `effective_from` (inclusive) and `effective_until` (exclusive). A pack is born with `status` `DRAFT`, `rule_count` 0, `activated_by_user_id`, `activated_at` and `retired_at` all null, and `created_by_user_id` set to the drafting engineer's `X-User-ID` — the value that will later block self-activation.

Three consistency rules are checked at drafting time and again at activation time. `effective_until` must be strictly after `effective_from`, or the draft is rejected with `ERR_INVALID_WINDOW`. `rule_weight` and `model_weight`, summed and rounded half up to two decimals, must come to exactly 1.00, or the request is rejected with `ERR_WEIGHTS_NOT_NORMALIZED`. And `review_floor_score` must be strictly below `decline_floor_score`, or the request is rejected with `ERR_INVALID_SCORE_BANDS`. Numeric fields outside their declared ranges are `ERR_VALIDATION`.

Rules are added to a pack only while it is still `DRAFT`; attempting to add one to an activated or retired pack is `ERR_RULE_PACK_NOT_DRAFT`. A rule takes its `rule_pack_id` from the pack segment of the path, and its body carries a `code`, a `signal_family`, a `points` value between 0 and 100 inclusive, an `evaluation_order` of at least 1, and an optional `hard_decline` flag defaulting to false. The ten recognised codes are `DEV_MULTI_ACCOUNT`, `DEV_EMULATOR`, `BEH_FAST_CHECKOUT`, `BEH_BULK_CART`, `VEL_CUSTOMER_1H`, `VEL_DEVICE_CARD_24H`, `ID_GEO_MISMATCH`, `ADDR_DROP_RISK`, `ADDR_FREIGHT_FORWARDER` and `PROMO_ADDRESS_ABUSE`, and each `code` may appear at most once in a given pack — a repeat is `ERR_DUPLICATE_RULE_CODE`. The declared `signal_family` must be the family the code actually belongs to: `DEV_` codes belong to `DEVICE`, `BEH_` codes to `BEHAVIORAL`, `VEL_` codes to `VELOCITY`, `ID_` codes to `IDENTITY`, `ADDR_` codes to `ADDRESS` and `PROMO_` codes to `PROMO`; a mismatch is `ERR_RULE_FAMILY_MISMATCH`. Each accepted rule increments the pack's `rule_count` by one. Rules are immutable and versionless (§2.5); `evaluation_order` fixes the walk order within the pack, with ties broken by `created_at` ascending.

Activation is where the segregation-of-duties and window-hygiene rules bite. On this path the checks run in the order: the pack must still be `DRAFT` (`ERR_RULE_PACK_NOT_DRAFT`); the acting engineer must not be the pack's `created_by_user_id` (`ERR_ACTIVATION_SEGREGATION_VIOLATION`); the window must clear the activation freeze buffer (`ERR_RULE_PACK_WINDOW_OVERLAP`); the pack must hold at least one rule (`ERR_RULE_PACK_EMPTY`); the weights must be normalised (`ERR_WEIGHTS_NOT_NORMALIZED`); and the bands must be correctly ordered (`ERR_INVALID_SCORE_BANDS`).

The freeze buffer deserves its own explanation. Aegis will not let two packs sit closer together in time than one hour, so that operators always have an hour of slack to notice a misconfiguration. Concretely, the candidate pack's window is inflated by one hour (3,600 seconds) at **both** ends, and that inflated window is compared against the un-inflated window of every pack whose `status` is `ACTIVE` or `RETIRED`. The candidate is accepted only if it lies entirely clear of each such pack — that is, only if the candidate's `effective_until` plus one hour is at or before the other pack's `effective_from`, or the other pack's `effective_until` plus one hour is at or before the candidate's `effective_from`. Exact adjacency is therefore **rejected**: two packs must be separated by strictly more than one hour of gap.

A successful activation sets `status` to `ACTIVE`, stamps `activated_at` with the current instant, records the acting engineer's `X-User-ID` as `activated_by_user_id`, and increments the pack's `version`. It also cascades: every **other** pack currently `ACTIVE` whose `effective_until` is at or before the newly activated pack's `effective_from` moves `ACTIVE → RETIRED`, receives `retired_at` at the current instant, and has its `version` incremented. A retired pack is terminal, and any assessment still sitting in `PENDING_SIGNALS` pinned to it can never be scored (§2.7).

### 3.3. Scoring Models and the Retraining Loop

The model side of the blend is owned by the same `PolicyEngineer` role. A model is drafted with a `model_version_label`, a `calibration_intercept` between −1.0 and 1.0 inclusive, a `calibration_slope` greater than 0.0 and at most 4.0, and an optional `trained_on_chargeback_cutoff_at`. It starts in `status` `DRAFT` with `training_segment_counts` null, `promoted_at` and `retired_at` null, and `scored_assessment_count` at 0. A supplied `trained_on_chargeback_cutoff_at` that lies after the current logical clock reading is rejected with `ERR_TRAINING_CUTOFF_IN_FUTURE`.

Whether the cutoff is supplied is what forks the lifecycle. A model with a non-null `trained_on_chargeback_cutoff_at` is a retrained model and must pass through the training gate. A model with a null cutoff is a **cold-start** model and is the only kind permitted to skip training. The five statuses are `DRAFT`, `TRAINING`, `SHADOW`, `ACTIVE` and `RETIRED`, driven by an `action` of `START_TRAINING`, `PUBLISH_SHADOW`, `REJECT`, `PROMOTE` or `RETIRE`. Any pairing of current status and requested action that is not one of the transitions below — including a shadow publication straight out of `DRAFT` when the cutoff is non-null — is rejected with `ERR_MODEL_TRANSITION_INVALID`. Every accepted action increments the model's `version` by one.

- **`DRAFT → TRAINING`** via `START_TRAINING`, permitted only when `trained_on_chargeback_cutoff_at` is non-null and the reason-code segment gate is satisfied. On success, `training_segment_counts` is **frozen** to the per-reason-code map the gate computed.
- **`DRAFT → SHADOW`** via `PUBLISH_SHADOW`, permitted only when `trained_on_chargeback_cutoff_at` is null — the cold-start branch.
- **`TRAINING → SHADOW`** via `PUBLISH_SHADOW`, with no further precondition.
- **`SHADOW → DRAFT`** via `REJECT`, which clears `training_segment_counts` back to null. This is the retraining loop: a rejected shadow model returns to the drawing board and may be trained again.
- **`SHADOW → ACTIVE`** via `PROMOTE`, which stamps `promoted_at` and cascades: the model previously in `ACTIVE` — there is at most one — moves to `RETIRED` with `retired_at` stamped and its own `version` incremented.
- **`ACTIVE → RETIRED`** via `RETIRE`, or as the promotion cascade above, stamping `retired_at`. Once the incumbent is retired, assessments pinned to it can no longer be scored, and newly opened assessments fail with `ERR_NO_ACTIVE_RISK_MODEL` until some model is promoted.

**The reason-code segment gate.** Retraining is only meaningful if the corpus actually contains fraud examples of each kind, so `START_TRAINING` counts, for each required reason-code segment in the fixed order `FRAUD_CNP` then `FRAUD_ATO`, the chargeback records whose `state` is `LOST`, whose `reason_code` is that segment, and whose `received_at` is **strictly earlier** than the model's `trained_on_chargeback_cutoff_at` — a dispute received at exactly the cutoff instant is excluded. Training proceeds only when **every** required segment holds at least 2 such records; otherwise the request is rejected with `ERR_TRAINING_SEGMENT_UNDERFILLED`, identifying the first deficient segment in that same fixed order. Non-fraud reason codes contribute to no segment at all, so a corpus of ten lost `PRODUCT_NOT_RECEIVED` disputes leaves both required segments at zero. On success the counted map is frozen into `training_segment_counts` and later disputes never mutate it.

**Calibration.** The two calibration terms are how a raw upstream probability becomes a point contribution. The upstream scoring service supplies `model_raw_probability` on each assessment as a four-decimal value between 0.0000 and 1.0000 inclusive. The server computes a calibrated probability as the model's `calibration_intercept` plus its `calibration_slope` multiplied by that raw probability; **clamps that probability** into the range 0.0000 to 1.0000; and only then multiplies by 100 and rounds half up to two decimal places to yield `model_points`, a value between 0.00 and 100.00. The clamp-before-scaling order is load-bearing: an intercept of 0.20 with a slope of 2.00 applied to a raw probability of 0.9000 gives 1.9800, which clamps to 1.0000 and yields `model_points` of 100.00 — not 198.00.

### 3.4. The Checkout Assessment Pipeline

Opening an assessment and scoring it are two separate steps, and the gap between them is where signals are gathered and the world can shift.

**Opening.** The checkout service opens an assessment with a payload naming the `customer_id`, the `device_profile_id`, the `shipping_address_id` and the `billing_address_id`, together with the order's `amount_cents` (an integer of at least 1), the `card_bin` (exactly six digits — the first six of the PAN, used as the distinct-BIN velocity input), the `ip_country` of the checkout IP as exactly two uppercase letters, the behavioural inputs `session_seconds` (a non-negative integer counting seconds from session start to checkout submit) and `cart_item_count` (at least 1), the upstream `model_raw_probability`, and an optional `promo_code` which is null when no promotion was applied. The customer must be `ACTIVE`, or the request is `ERR_CUSTOMER_ACCOUNT_LOCKED`. The row is created in state `PENDING_SIGNALS` with every score field null, `hard_decline_triggered` false, `applied_exception_id` null, `outcome_label` `UNKNOWN`, `final_disposition` and `decided_at` null, and both decisioning assets pinned per §2.7.

**Scoring** runs the entire pipeline in a single request and resolves a three-way fork. Before any computation, four gates are checked in this order: the assessment must still be in `PENDING_SIGNALS`, or the request is `ERR_ASSESSMENT_ALREADY_SCORED` — this is also the idempotency guard, so a second scoring attempt on the same assessment always fails here; the customer's `account_status` must be `ACTIVE`, or `ERR_CUSTOMER_ACCOUNT_LOCKED`; the customer's `ato_posture` must be anything other than `CONTAINED`, or `ERR_CUSTOMER_ATO_CONTAINED`; and the pinned pack and model must both still be `ACTIVE`, or `ERR_RULE_PACK_NOT_ACTIVE` and then `ERR_RISK_MODEL_NOT_ACTIVE`.

**Step one — velocity windows.** Three counts are taken against the logical clock as it reads at the scoring instant. All three windows have **inclusive** bounds at both ends, so a sibling row created at exactly the window's opening instant is still inside it.

- `velocity_customer_assessment_count_1h` is the number of assessments belonging to the same customer, other than the one being scored, whose `created_at` falls within the hour ending now — that is, at or after one hour (3,600 seconds) before now and at or before now. State is deliberately **not** filtered: abandoned attempts still sitting in `PENDING_SIGNALS` count as velocity, because a burst of attempts is the signal.
- `velocity_device_distinct_card_bin_count_24h` is the number of distinct `card_bin` values across the assessments on the same device whose `created_at` falls within the 24 hours (86,400 seconds) ending now, **together with** the assessment being scored, whose own `card_bin` is always included. Its minimum possible value is therefore 1.
- `velocity_promo_address_count_30d` is the number of assessments other than this one that carry a non-null `promo_code` and whose shipping address resolves to the same canonical cluster as this assessment's shipping address, with `created_at` inside the 30 days (2,592,000 seconds) ending now. This assessment is excluded from the count even when its own `promo_code` is non-null.

**Step two — the rule walk.** The pinned pack's rules are evaluated **one at a time** in ascending `evaluation_order`, ties broken by `created_at` ascending. The walk **short-circuits** on the first firing rule whose `hard_decline` is true: rules after that point are never evaluated and never appear in `triggered_rule_codes`.

Before the walk, the server determines whether the `ADDRESS` family is suppressed for this assessment. Suppression applies when there exists a policy exception that is in state `APPROVED`, belongs to this assessment's customer, has `scope` `ADDRESS_WHITELIST`, whose `effective_from` is at or before now while its `expires_at` is strictly after now, and whose `whitelisted_address_id` resolves to the same canonical cluster as this assessment's shipping address.

Each rule's predicate is fixed by its `code`:

- `DEV_MULTI_ACCOUNT` fires when the device's `distinct_customer_count` is at least 3, read at the value it holds **before** this assessment's own recompute.
- `DEV_EMULATOR` fires when the device's `emulator_flag` is true.
- `BEH_FAST_CHECKOUT` fires when `session_seconds` is fewer than 45.
- `BEH_BULK_CART` fires when `cart_item_count` is at least 10.
- `VEL_CUSTOMER_1H` fires when `velocity_customer_assessment_count_1h` is at least 3.
- `VEL_DEVICE_CARD_24H` fires when `velocity_device_distinct_card_bin_count_24h` is at least 3.
- `ID_GEO_MISMATCH` fires when the assessment's `ip_country` differs from the `country_code` of the billing address.
- `ADDR_DROP_RISK` fires when the shipping cluster root's `drop_risk_state` is `KNOWN_DROP`.
- `ADDR_FREIGHT_FORWARDER` fires when the shipping address row's own `classification` is `FREIGHT_FORWARDER`.
- `PROMO_ADDRESS_ABUSE` fires when the assessment's `promo_code` is non-null **and** `velocity_promo_address_count_30d` is at least 2.

A rule fires only if its predicate holds **and** it is not an `ADDRESS`-family rule under suppression. A suppressed `ADDRESS` rule is skipped entirely: it contributes no points, is absent from `triggered_rule_codes`, and cannot short-circuit the walk even when its `hard_decline` is true. It does, however, set `applied_exception_id` to the whitelisting exception.

From the walk: `rule_score` is the sum of `points` over the fired rules, capped at 100; `triggered_rule_codes` lists the fired codes in evaluation order; `hard_decline_triggered` is true exactly when some fired rule had `hard_decline` true; and `primary_signal_family` is the `signal_family` of the fired rule with the highest `points`, with ties broken in favour of the **lowest** `evaluation_order`, or `MODEL` when no rule fired at all.

**Step three — blending.** `model_points` is calibrated as described in §3.3, and `blended_score` combines the two components according to the pinned pack's `blend_mode`. Both variants cap the result at 200.00 and round half up to two decimal places, and each is specified with equal force:

- Under `WEIGHTED`, the blended score is the pack's `rule_weight` multiplied by `rule_score`, plus the pack's `model_weight` multiplied by `model_points`, with **one** rounding step applied to the whole weighted sum. The two products are **not** rounded individually. With a `rule_weight` of 0.40, a `model_weight` of 0.60, a `rule_score` of 20 and `model_points` of 53.25, the two products are 8.00 and 31.95 and the blended score is 39.95.
- Under `RULE_DOMINANT`, the model contribution is damped and the sum is then uplifted, in **two separately rounded steps**. First, an inner damped model term is formed by multiplying `model_points` by 0.35 and rounding half up to **one** decimal place. Second, that inner term is added to `rule_score`, the sum is multiplied by 1.25, and the result is rounded half up to two decimal places. The nesting order is part of the contract: with the same inputs, the inner term is 0.35 × 53.25 = 18.6375 rounded to 18.6, the uplift gives (20 + 18.6) × 1.25 = 48.25, and the blended score is 48.25 — whereas collapsing the two steps into one would give 48.30, which is wrong. In this mode `rule_weight` and `model_weight` are ignored entirely, although they are still required to sum to 1.00.

**Step four — the band decision.** `decision` and `decision_reason` are resolved by taking the **first** matching clause of this pinned precedence, and once set at scoring, `decision` is frozen — manual review never rewrites it.

1. `hard_decline_triggered` is true → `decision` `DECLINE`, `decision_reason` `HARD_RULE`. No policy exception of any kind can rescue a hard decline.
2. `blended_score` is greater than or equal to the pack's `decline_floor_score` → `decision` `DECLINE`, `decision_reason` `SCORE_BAND`. A band-stage exception cannot rescue the decline band either. The comparison is inclusive: a score exactly equal to `decline_floor_score` declines.
3. `blended_score` is greater than or equal to the pack's `review_floor_score` (again inclusive, so a score exactly equal to `review_floor_score` lands here) → if an eligible band-stage exception exists, `decision` is `APPROVE` with `decision_reason` `POLICY_EXCEPTION` and `applied_exception_id` set to that exception; otherwise `decision` is `REVIEW` with `decision_reason` `SCORE_BAND`.
4. Otherwise → `decision` `APPROVE`, `decision_reason` `SCORE_BAND`.

A **band-stage exception** is eligible when it is in state `APPROVED`, belongs to this assessment's customer, has `scope` `AUTO_APPROVE_UNDER_AMOUNT`, has an `effective_from` at or before now and an `expires_at` strictly after now, and has a `max_amount_cents` at least as large as the order's `amount_cents`. When several qualify, the one with the highest `max_amount_cents` wins, and among equals the one created earliest. A band-stage exception always wins the `applied_exception_id` slot; the rule-stage `ADDRESS_WHITELIST` exception fills that slot only when no band-stage exception was applied.

**Step five — the three-way fork.** Whichever branch is taken, `velocity_*` fields, `rule_score`, `model_points`, `blended_score`, `triggered_rule_codes`, `hard_decline_triggered`, `primary_signal_family`, `decision` and `decision_reason` are all written, and the pinned model's `scored_assessment_count` increments by one. Beyond that the branches diverge sharply, and each is specified in full.

*The approve branch* — `PENDING_SIGNALS → DECIDED_APPROVE`, taken when the band resolution yields `APPROVE` (whether by score band or by policy exception) and `hard_decline_triggered` is false. It sets `final_disposition` to `APPROVED`, stamps `decided_at` with the current instant, and freezes `good_customer_at_decision` to the customer's `good_customer_flag` as it stands at that instant — a snapshot retained for insult-rate audits and never revised. It increments the customer's `approved_count` by one and their `lifetime_net_approved_cents` by the order's `amount_cents`, then recomputes `good_customer_flag` and increments the customer's `version`. It recomputes the shipping cluster root's `distinct_customer_count`, `approved_use_count`, `promo_redemption_count`, `drop_risk_state` and `reshipper_confidence`, and the device's `distinct_customer_count`, `approved_use_count` and `reputation`. And when `applied_exception_id` is non-null, it increments that exception's `consumed_count` by one and its `version` by one.

*The review branch* — `PENDING_SIGNALS → IN_REVIEW`, taken when the band resolution yields `REVIEW`, meaning the score reached the review floor and no band-stage exception applied. `decision` is `REVIEW` and `decision_reason` is `SCORE_BAND`. There is **no ledger movement** in this branch: `lifetime_net_approved_cents`, `approved_count` and `declined_count` are all left untouched, because nothing has been decided commercially yet. Instead the branch creates a review case, described in §3.6, in state `QUEUED`. It recomputes the device's `distinct_customer_count` and `reputation`, and the shipping cluster root's `distinct_customer_count`, `drop_risk_state` and `reshipper_confidence`.

*The decline branch* — `PENDING_SIGNALS → DECIDED_DECLINE`, taken when `hard_decline_triggered` is true or `blended_score` reached the decline floor. `decision_reason` is `HARD_RULE` when a hard-decline rule fired and `SCORE_BAND` otherwise — note that a hard-decline rule forces this branch even when `blended_score` sits below `review_floor_score`. It sets `final_disposition` to `DECLINED`, stamps `decided_at`, and freezes `good_customer_at_decision` the same way the approve branch does. It increments the customer's `declined_count` by one and their `version` by one, and leaves `lifetime_net_approved_cents` unchanged. It recomputes the device's `distinct_customer_count` and `reputation`, and the shipping cluster root's `distinct_customer_count`, `drop_risk_state` and `reshipper_confidence`.

### 3.5. Policy Exceptions for High-Value and Business Accounts

Some accounts earn the right to bypass part of the machinery. A `RiskAnalyst` — and only a risk analyst — requests a policy exception on behalf of a customer, naming the `customer_id`, a `scope`, a `max_amount_cents` ceiling of at least 1, the window `effective_from` (inclusive) and `expires_at` (exclusive), a written `justification`, and, depending on scope, a `whitelisted_address_id`. The requesting analyst's `X-User-ID` is recorded as `requested_by_analyst_id`; the row starts in state `REQUESTED` with `consumed_count` 0, `approved_by_analyst_id` null, `decided_at` null and `decision_note` null.

The two scopes intervene at different stages of scoring and should not be confused. `AUTO_APPROVE_UNDER_AMOUNT` is a **band-stage** override: it does not change which rules fire, it rescues an order that landed in the review band, as clause 3a of §3.4. `ADDRESS_WHITELIST` is a **rule-stage** suppression: it removes the whole `ADDRESS` signal family from the walk for orders shipping into the whitelisted cluster.

Request-time validation runs in this order. The beneficiary customer must be `ACTIVE`, or the request is `ERR_CUSTOMER_ACCOUNT_LOCKED` — and this outranks every fiscal check below it, so a locked customer masks a tier-cap violation rather than the other way round. Scope coherence follows: `ADDRESS_WHITELIST` requires a non-null `whitelisted_address_id`, or `ERR_EXCEPTION_SCOPE_ADDRESS_REQUIRED`; `AUTO_APPROVE_UNDER_AMOUNT` requires `whitelisted_address_id` to be null, or `ERR_EXCEPTION_ADDRESS_NOT_ALLOWED`. Then `expires_at` must be strictly after `effective_from`, or `ERR_INVALID_WINDOW`. Then window exclusivity: no other exception for the **same customer with the same scope** whose state is `REQUESTED` or `APPROVED` may overlap the candidate's half-open window — overlap means the candidate's `expires_at` is after the other's `effective_from` *and* the other's `expires_at` is after the candidate's `effective_from`. Exact adjacency, where the candidate's `effective_from` equals the other's `expires_at`, is explicitly **allowed**; rows in `REJECTED` or `REVOKED` never block. A collision is `ERR_EXCEPTION_WINDOW_OVERLAP`.

Two fiscal rules close the request path. The requested `max_amount_cents` must not exceed the beneficiary's tier ceiling — 50,000 cents for `STANDARD`, 500,000 cents for `HIGH_VALUE`, and 2,000,000 cents for `BUSINESS`. The ceiling is **inclusive**: a request exactly equal to the cap is accepted, and only a request above it is rejected with `ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP`. Separately, the `AUTO_APPROVE_UNDER_AMOUNT` scope is available only to `HIGH_VALUE` and `BUSINESS` customers; a `STANDARD` customer asking for it is rejected with `ERR_EXCEPTION_TIER_NOT_ELIGIBLE`. The `ADDRESS_WHITELIST` scope is open to every tier and still honours the tier ceiling.

Deciding an exception belongs exclusively to a `ReviewLead`, who supplies an `action` of `APPROVE`, `REJECT` or `REVOKE`, the mandatory `expected_customer_version` of §2.8, and an optional `decision_note`. Only three transitions are declared, and any other pairing of current state with requested action is `ERR_EXCEPTION_STATE_INVALID`: `APPROVE` and `REJECT` both require `REQUESTED`, and `REVOKE` requires `APPROVED`. On this path the checks run in the order: for `APPROVE`, the customer must be `ACTIVE` (`ERR_CUSTOMER_ACCOUNT_LOCKED`); then the state-and-action pairing; then the stale-customer-version check (`ERR_STALE_CUSTOMER_VERSION`); then, for `APPROVE` and `REJECT` only, the segregation check against `requested_by_analyst_id` (`ERR_DECISION_SEGREGATION_VIOLATION`).

- `REQUESTED → APPROVED` records the deciding lead's `X-User-ID` as `approved_by_analyst_id`, stamps `decided_at` and stores `decision_note`. Because the customer's policy surface has changed, the customer's `version` increments by one alongside the exception's own.
- `REQUESTED → REJECTED` stamps `decided_at` and stores `decision_note`, leaves `approved_by_analyst_id` null, and increments both the customer's and the exception's `version`.
- `APPROVED → REVOKED` stamps `decided_at`, preserves `consumed_count` as a historical record, and increments both versions. Revocation is exempt from the segregation check — the requester may revoke their own exception. Assessments scored after the revocation instant no longer see the exception; those already scored keep their `applied_exception_id`.

### 3.6. Manual Review: Queue Staffing, Escalation and Resolution

**Analysts.** A platform administrator registers an analyst with a `display_name`, a `seniority` of `JUNIOR`, `SENIOR` or `LEAD`, a non-empty `skill_families` array drawn from `DEVICE`, `BEHAVIORAL`, `VELOCITY`, `IDENTITY`, `ADDRESS`, `PROMO` and `MODEL`, and a `shift_capacity_cases` of at least 1 giving the maximum number of cases the analyst may hold simultaneously. An empty `skill_families` array, or one containing a value outside that enumeration, is `ERR_VALIDATION`. The analyst begins with `status` `AVAILABLE` and both `open_case_count` and `resolved_case_count` at 0. The roster's `status` axis moves among `AVAILABLE`, `OFF_SHIFT` and `SUSPENDED`, and only `AVAILABLE` analysts are assignment-eligible.

Moving an analyst away from `AVAILABLE` triggers the **shift-release cascade**, whose links are: every review case in state `ASSIGNED` held by that analyst moves `ASSIGNED → QUEUED`, with its `assigned_analyst_id` and `assigned_at` cleared and its `requeue_count` incremented by one; the analyst's `open_case_count` is set outright to 0, restoring the review-capacity ledger of §2.9; and the analyst's `version` increments by one.

**Cases.** A review case is never created by a client call. It is created by the review branch of §3.4, which sets its `assessment_id` to the assessment that scored into the review band, copies `primary_signal_family` from that assessment (the value later matched against analyst skills), stamps `sla_due_at` at four hours — 14,400 seconds — after the case's `created_at`, computes an initial `priority_score`, and leaves `assigned_analyst_id`, `escalated_by_analyst_id`, `assigned_at`, `resolved_at`, `resolved_late` and `resolution_note` null with `requeue_count` and `escalation_count` at 0. Case state moves among `QUEUED`, `ASSIGNED`, `ESCALATED`, `RESOLVED_APPROVE` and `RESOLVED_DECLINE`; the last two are terminal.

**Priority.** `priority_score` is recomputed at case creation, on every `ASSIGNED → ESCALATED` transition, and by the chargeback cascade of §3.8. It is the sum of five terms, rounded half up to two decimal places: half of the assessment's `blended_score`; an amount term equal to the order's `amount_cents` divided by 10,000 and rounded half up to two decimals, then capped at 20.00 (a cap the term reaches at an order of 200,000 cents); a tier boost of 0.00 for `STANDARD`, 10.00 for `HIGH_VALUE` and 15.00 for `BUSINESS`; a good-customer boost of 20.00 when the customer's `good_customer_flag` is true at recompute time and 0.00 otherwise; and an escalation boost of 15.00 when the case's `escalation_count` is greater than zero and 0.00 otherwise. Worked through: a case on a `STANDARD` good customer with a `blended_score` of 50.00 and an order of 75,000 cents, never escalated, scores 25.00 + 7.50 + 0.00 + 20.00 + 0.00 = 52.50. Unlike the assessment's frozen `good_customer_at_decision`, this term reads the customer's **current** flag, which is exactly what lets a confirmed fraud elsewhere on the account re-price the queue — the same case, after the flag is lost, scores 32.50.

**Explicit staffing.** A `ReviewLead` assigns a case to a named analyst by supplying `analyst_id` and `expected_analyst_version`. The checks run in this order: the case's state must permit assignment, meaning `QUEUED` or `ESCALATED` (`ERR_CASE_STATE_INVALID`); the stale-analyst-version check (`ERR_STALE_ANALYST_VERSION`); for an `ESCALATED` case, the analyst must not be the one recorded in `escalated_by_analyst_id` (`ERR_ESCALATION_SEGREGATION_VIOLATION`); for an `ESCALATED` case, the analyst's `seniority` must be `LEAD` (`ERR_ESCALATED_REQUIRES_LEAD`); the case's `primary_signal_family` must be among the analyst's `skill_families` (`ERR_ANALYST_SKILL_MISMATCH`); the analyst's `status` must be `AVAILABLE` (`ERR_ANALYST_NOT_AVAILABLE`); and finally the analyst's `open_case_count` must be strictly below their `shift_capacity_cases` (`ERR_ANALYST_CAPACITY_EXCEEDED`). That ordering matters: the lead-seniority requirement is reported ahead of the capacity failure when both apply.

A successful assignment — `QUEUED → ASSIGNED` or `ESCALATED → ASSIGNED`, the latter closing the escalation cycle — sets `assigned_analyst_id` and stamps `assigned_at` at the current instant, increments the analyst's `open_case_count` by one and the analyst's `version` by one, and increments the case's own `version` by one.

**Automatic staffing.** A `ReviewLead` may instead ask the server to choose. Automatic staffing takes no request body at all and no version field, because the server reads the analyst it selects. It filters the roster to analysts whose `status` is `AVAILABLE`, whose `skill_families` include the case's `primary_signal_family`, whose `open_case_count` is strictly below their `shift_capacity_cases`, and — when the case is `ESCALATED` — whose `seniority` is `LEAD` and whose identity differs from the case's `escalated_by_analyst_id`. The surviving pool is then ordered by a pinned key sequence, first key winning: remaining headroom, defined as `shift_capacity_cases` minus `open_case_count`, **descending**; then seniority rank **ascending**, treating `JUNIOR` as lower than `SENIOR` and `SENIOR` as lower than `LEAD`, so the cheapest qualified analyst is taken first; then `created_at` ascending; then `id` ascending, which makes the order total and leaves no ties. The head of that order receives the case, with exactly the same side effects as an explicit assignment. An empty pool is an error — `ERR_NO_ELIGIBLE_ANALYST` — never a silent no-op. As with explicit staffing, a case whose state is neither `QUEUED` nor `ESCALATED` is `ERR_CASE_STATE_INVALID`.

**Resolution and escalation.** A `RiskAnalyst` or a `ReviewLead` closes out a case with an `action` of `APPROVE`, `DECLINE` or `ESCALATE`, plus an optional `resolution_note` recorded at either resolution or escalation. All three actions require the case to be in state `ASSIGNED`; anything else is `ERR_CASE_STATE_INVALID`, checked before ownership. Ownership is then enforced asymmetrically: a `RiskAnalyst` may act only on a case whose `assigned_analyst_id` equals their own `X-User-ID`, and otherwise receives `ERR_NOT_CASE_OWNER`, whereas a `ReviewLead` may resolve any `ASSIGNED` case. Escalation additionally requires that the acting principal be the case's assigned analyst.

- `ASSIGNED → RESOLVED_APPROVE` stamps `resolved_at` at the current instant, stores `resolution_note`, and sets `resolved_late` to true exactly when `resolved_at` is later than `sla_due_at`. It decrements the analyst's `open_case_count` by one, increments their `resolved_case_count` by one and their `version` by one. It then cascades the assessment `IN_REVIEW → DECIDED_APPROVE`: `decision_reason` becomes `MANUAL_REVIEW` while `decision` **stays** `REVIEW`, `final_disposition` becomes `APPROVED`, `decided_at` is stamped, the customer's `approved_count` rises by one and `lifetime_net_approved_cents` by the order's `amount_cents`, `good_customer_flag` is recomputed and the customer's `version` increments; the shipping cluster root's `approved_use_count`, `promo_redemption_count`, `drop_risk_state` and `reshipper_confidence` are recomputed, as are the device's `approved_use_count` and `reputation`.
- `ASSIGNED → RESOLVED_DECLINE` stamps `resolved_at` and evaluates `resolved_late` the same way, decrements the analyst's `open_case_count` by one and increments their `version` by one when an analyst held the case, and cascades the assessment `IN_REVIEW → DECIDED_DECLINE`: `decision_reason` becomes `MANUAL_REVIEW`, `final_disposition` becomes `DECLINED`, `decided_at` is stamped, the customer's `declined_count` and `version` each rise by one, and the device's `reputation` and the shipping cluster root's `drop_risk_state` are recomputed.
- `ASSIGNED → ESCALATED` records the acting analyst as `escalated_by_analyst_id`, clears `assigned_analyst_id` back to null, increments `escalation_count` by one, decrements the previously assigned analyst's `open_case_count` by one and increments that analyst's `version` by one, and recomputes `priority_score` — which now picks up the escalation boost. The case returns to the queue awaiting a `LEAD`.

Two further arrivals at `RESOLVED_DECLINE` come from the containment cascade of §3.7 rather than from an analyst: a case in `QUEUED` and a case in `ESCALATED` both move to `RESOLVED_DECLINE` when their assessment is force-declined by containment. Both stamp `resolved_at` and evaluate `resolved_late`, and neither touches any analyst counter, because in both states `assigned_analyst_id` is null.

### 3.7. Account-Takeover Detection and Step-Up Containment

Logins and sensitive profile changes are scored on their own axis. The checkout service records an authentication event with a `customer_id`, a `device_profile_id`, an `event_type` of `LOGIN`, `PASSWORD_CHANGE`, `EMAIL_CHANGE`, `SHIP_ADDRESS_ADD` or `PAYMENT_INSTRUMENT_ADD`, an `ip_country` of exactly two uppercase letters, and an optional `prior_password_change_hours` giving the hours since the account's last password change as the caller understands it, null when unknown. That last field is retained for analyst context only; it is not an input to any score.

Every event is scored immediately, reading the customer and the device as they stand **before** this event's own side effects land. `device_first_seen_for_customer` is true when nothing in the record already pairs this customer with this device — no other authentication event, and no checkout assessment at all. `ato_score` is then the sum of four terms, capped at 100.00 and rounded half up to two decimal places:

- An event base determined by `event_type`: 10.00 for `LOGIN`, 25.00 for `PASSWORD_CHANGE`, 30.00 for `EMAIL_CHANGE`, 20.00 for `SHIP_ADDRESS_ADD` and 35.00 for `PAYMENT_INSTRUMENT_ADD`.
- A geography term of 25.00 when the event's `ip_country` differs from the customer's `home_country`, and 0.00 when they match.
- A device term that is 20.00 whenever `device_first_seen_for_customer` is true. Otherwise it is driven by the device's `reputation`: 40.00 for `BLOCKED`, 15.00 for `SUSPECT`, and 0.00 for `NEW` or `TRUSTED`. First-seen **suppresses** the reputation term; the two are never summed.
- A failure term equal to the customer's `failed_login_count` multiplied by 5.00, capped at 15.00.

The score freezes the event's `outcome`, which is immutable thereafter: 75.00 or above is `BLOCKED`, 45.00 or above (but below 75.00) is `STEP_UP_REQUIRED`, and anything lower is `ALLOWED`. A `PASSWORD_CHANGE` from a foreign IP on a known device with no prior failures scores 25.00 + 25.00 = 50.00 and lands in `STEP_UP_REQUIRED`; a `PAYMENT_INSTRUMENT_ADD` from a foreign IP with the failure term at its 15.00 cap scores exactly 75.00 and lands in `BLOCKED` right at the floor. Recording an event also recomputes the device's `distinct_customer_count` and `reputation`, since authentication events feed the distinct-customer signal.

The event's second axis, `challenge_state`, starts at `ISSUED` when `outcome` is `STEP_UP_REQUIRED` and at `NONE` otherwise, and moves among `NONE`, `ISSUED`, `PASSED`, `FAILED` and `EXPIRED`, with `PASSED` and `EXPIRED` terminal. A `STEP_UP_REQUIRED` event sets `challenge_method` to `OTP_SMS` and `challenge_expires_at` to fifteen minutes — 900 seconds — after the current instant, and moves the customer's `ato_posture` `CLEAR → WATCH`, incrementing the customer's `version`. A `BLOCKED` event leaves `challenge_state` at `NONE` and instead drives the customer's `ato_posture` straight to `CONTAINED`, firing the containment cascade below and incrementing the customer's `version`. Both posture moves require that the customer's `account_status` not be `CLOSED`.

The challenge itself is driven by the checkout service with an `action` of `PASS`, `FAIL`, `REISSUE` or `EXPIRE`, plus an optional `challenge_method` of `OTP_SMS`, `OTP_EMAIL` or `THREE_DS`. Checks run in this order: the current `challenge_state` must permit the action — `PASS`, `FAIL` and `EXPIRE` all require `ISSUED` and `REISSUE` requires `FAILED`, otherwise `ERR_CHALLENGE_STATE_INVALID`; for `PASS`, `FAIL` and `REISSUE`, the clock must still be strictly before `challenge_expires_at`, otherwise `ERR_CHALLENGE_EXPIRED`; for `EXPIRE`, the clock must be at or after `challenge_expires_at`, otherwise `ERR_CHALLENGE_NOT_EXPIRED`; and for `REISSUE`, the attempt budget must not be exhausted, otherwise `ERR_CHALLENGE_ATTEMPTS_EXHAUSTED`. Every accepted action increments the event's `version` by one.

- `ISSUED → PASSED` sets the customer's `failed_login_count` back to 0 and moves `ato_posture` `WATCH → CLEAR`, incrementing the customer's `version`.
- `ISSUED → FAILED` increments the event's `challenge_attempts` by one and the customer's `failed_login_count` by one. When that increment carries `challenge_attempts` to 3 — the attempt budget — it is the **first link of the containment chain**: the customer's `ato_posture` moves `WATCH → CONTAINED`, firing the remaining links.
- `FAILED → ISSUED` is the retry cycle: it sets `challenge_method` to the supplied method, defaulting to `OTP_SMS` when none is given, and resets `challenge_expires_at` to fifteen minutes after the current instant, leaving `challenge_attempts` **unchanged**. It requires `challenge_attempts` still below 3 and requires that the customer not be `CONTAINED` — and because containment happens exactly when the third failure lands, an exhausted budget and a contained customer arrive together and are reported as `ERR_CHALLENGE_ATTEMPTS_EXHAUSTED`.
- `ISSUED → EXPIRED` has no customer-side effect at all: `ato_posture` stays at `WATCH` and `failed_login_count` is unchanged. This is the only route to `EXPIRED`.

**The containment cascade.** Whether reached by a `BLOCKED` event (`CLEAR → CONTAINED`) or by the third challenge failure (`WATCH → CONTAINED`), containment runs the identical four-link chain, and both entry points must produce identical results:

1. `ato_posture` becomes `CONTAINED` and the customer's `version` increments by one.
2. `account_status` is forced to `LOCKED` with `locked_reason` set to `ATO_CONTAINMENT`.
3. Every one of that customer's assessments currently in state `IN_REVIEW` moves to `DECIDED_DECLINE` with `decision_reason` `ATO_CONTAINMENT` and `final_disposition` `DECLINED`, and the customer's `declined_count` rises by one **per assessment** so moved.
4. Each such assessment's review case moves to `RESOLVED_DECLINE`, and where that case had a non-null `assigned_analyst_id`, that analyst's `open_case_count` is decremented by one and their `version` incremented by one.

### 3.8. Chargeback Outcomes, Guarantee Settlement and the Fraud Feedback Loop

A dispute is filed by a platform administrator against an approved order, naming the `assessment_id`, a `reason_code` of `FRAUD_CNP`, `FRAUD_ATO`, `PRODUCT_NOT_RECEIVED` or `SUBSCRIPTION_CANCELED`, the disputed `amount_cents` (at least 1), a `liability_shift` boolean recording whether the issuer bore liability through 3-D Secure authentication, the network's `received_at` instant, and an optional `evidence_note`. Filing checks run in this order: the referenced assessment must be in state `DECIDED_APPROVE`, or `ERR_CHARGEBACK_ASSESSMENT_NOT_APPROVED`; `received_at` must not precede the assessment's `decided_at`, or `ERR_CHARGEBACK_BEFORE_DECISION`; and the disputed `amount_cents` must not exceed the order's own `amount_cents`, or `ERR_CHARGEBACK_AMOUNT_EXCEEDS_ORDER`. The record starts in state `RECEIVED` with `guarantee_state` `NOT_APPLICABLE`, `guarantee_denial_reason` null, all three guarantee amounts at 0 and `resolved_at` null.

The dispute is then driven by an `action` of `REPRESENT`, `WIN` or `LOSE`, with an optional `evidence_note`. Any pairing of current state with action other than the four declared transitions is `ERR_CHARGEBACK_TRANSITION_INVALID`.

- `RECEIVED → REPRESENTED` via `REPRESENT` stores the `evidence_note` representment summary and increments `version`.
- `REPRESENTED → WON` via `WIN` stamps `resolved_at`, leaves `guarantee_state` at `NOT_APPLICABLE` — the guarantee waterfall runs only on a loss — and sets the assessment's `outcome_label` to `LEGIT`. The customer's `lifetime_net_approved_cents` is deliberately unchanged: a won dispute confirms the order was good.
- `RECEIVED → LOST` via `LOSE`, accepting liability without representment, and `REPRESENTED → LOST` via `LOSE` after a failed representment, both run the identical cascade below.

**The loss cascade** has five links, and every one of them must land:

1. `state` becomes `LOST`, `resolved_at` is stamped, `version` increments, and the guarantee waterfall runs, filling `guarantee_state`, `guarantee_denial_reason`, `guarantee_eligible_cents`, `guarantee_fee_cents` and `guarantee_reimbursed_cents`.
2. **Only when `reason_code` is `FRAUD_CNP` or `FRAUD_ATO`**, the assessment's `outcome_label` is set to `FRAUD`.
3. Caused by link 2: the customer's `lifetime_net_approved_cents` is decremented by the **assessment's** `amount_cents` — never the disputed amount, which may be partial — `confirmed_fraud_count` increments by one, and the customer's `version` increments by one.
4. Caused by link 3: the customer's `good_customer_flag` is recomputed, and because `confirmed_fraud_count` is now above zero it is forced to false.
5. Caused by link 4, and **only when the flag actually flipped**: `priority_score` is recomputed for every review case belonging to that customer's assessments whose state is `QUEUED`, `ASSIGNED` or `ESCALATED`, each such case's `version` incrementing by one. This is how a confirmed fraud in one corner of the account re-prices the whole queue.

Also caused by link 2, the device profile's counters and `reputation` are recomputed, and the shipping cluster root's counters, `drop_risk_state` and `reshipper_confidence` are recomputed. Both of those are recounts over assessments rather than increments (§2.9), so a second lost dispute on the same order leaves them exactly where they were — as it leaves the ledger and `confirmed_fraud_count`, per the idempotence guard, because the assessment's `outcome_label` is already `FRAUD` and links 2 through 5 therefore do not fire again.

A non-fraud `reason_code` stops after link 1 entirely: `outcome_label` stays `UNKNOWN`, no ledger reversal occurs, and the guarantee comes back `DENIED` with reason `REASON_NOT_COVERED`.

**The guarantee waterfall.** Aegis backs some declined-fraud losses with a reimbursement guarantee, and eligibility is decided by four tests applied in a pinned order. The **first** test that fails decides `guarantee_denial_reason`, and no later test is evaluated:

1. `liability_shift` is true → `DENIED` with reason `LIABILITY_SHIFTED`.
2. `reason_code` is neither `FRAUD_CNP` nor `FRAUD_ATO` → `DENIED` with reason `REASON_NOT_COVERED`.
3. The assessment's `applied_exception_id` is non-null → `DENIED` with reason `EXCEPTION_OVERRIDE`; a merchant that overrode the system's judgement wears the loss.
4. The assessment's `decision` is anything other than `APPROVE`, **or** its `decision_reason` is `MANUAL_REVIEW` → `DENIED` with reason `DECISION_NOT_ELIGIBLE`; only a machine approval is guaranteed.
5. Otherwise → `REIMBURSED`, with `guarantee_denial_reason` null.

Because test 1 precedes test 2, a liability-shifted `PRODUCT_NOT_RECEIVED` dispute denies with `LIABILITY_SHIFTED`, not `REASON_NOT_COVERED`. A `DENIED` outcome leaves `guarantee_eligible_cents`, `guarantee_fee_cents` and `guarantee_reimbursed_cents` all at 0. A `REIMBURSED` outcome sets `guarantee_eligible_cents` to the smallest of three figures — the disputed `amount_cents`, the order's own `amount_cents`, and the programme coverage cap of 500,000 cents; sets `guarantee_fee_cents` to the programme fee of 250 basis points, that is 2.50 percent of the eligible amount, **floored** to whole cents and never rounded up; and sets `guarantee_reimbursed_cents` to the eligible amount minus the fee. A 75,000-cent dispute on a 75,000-cent machine-approved order with no exception and no liability shift therefore yields an eligible amount of 75,000, a fee of 1,875 and a reimbursement of 73,125.

### 3.9. Measuring False Positives

The point of all this machinery is to catch fraud without insulting good customers, and the insult side of that trade is measured per rule pack. The report is available to a `PolicyEngineer` or a `ReviewLead` and takes a single selector, `cohort`, which defaults to `DECISION_COHORT` and may instead be `GOOD_CUSTOMER_COHORT`.

Both variants draw from the same population: assessments pinned to the pack in question whose `state` is either `DECIDED_APPROVE` or `DECIDED_DECLINE`. Assessments still in `PENDING_SIGNALS` or `IN_REVIEW` are excluded from both the numerator and the denominator — a pending order is not yet a decision anyone can be judged on. Cohort membership is resolved from the **frozen snapshot** `good_customer_at_decision` stored on the assessment, never from the customer's `good_customer_flag` as it stands now, and the evaluation order is: resolve membership from the snapshot, partition into numerator and denominator, divide, and round the **quotient** to four decimal places. The counts themselves are never rounded.

- Under `DECISION_COHORT`, the denominator is every terminal assessment on the pack, and the numerator is those whose `final_disposition` is `DECLINED` and whose `outcome_label` is not `FRAUD` — declines that fraud never justified.
- Under `GOOD_CUSTOMER_COHORT`, the denominator narrows to terminal assessments whose `good_customer_at_decision` is true, and the numerator is those of *them* whose `final_disposition` is `DECLINED` and whose `outcome_label` is not `FRAUD`.

`insult_rate` is the numerator divided by the denominator, rounded half up to four decimal places, and is reported as 0.0000 when the denominator is 0. Alongside it, and computed over the same cohort, the report carries the selected `cohort` name, the `denominator_count`, an `approved_count` of assessments whose `final_disposition` is `APPROVED`, a `declined_count` of assessments whose `final_disposition` is `DECLINED`, a `false_positive_count` equal to the insult numerator, a `confirmed_fraud_count` of assessments whose `outcome_label` is `FRAUD`, and a `fraud_capture_rate` — the number of cohort assessments that are both labelled `FRAUD` and were `DECLINED`, divided by the number labelled `FRAUD`, rounded half up to four decimal places and reported as 0.0000 when that denominator is 0.

One consequence of freezing the snapshot is worth noting: when a lost dispute later flips an assessment's `outcome_label` to `FRAUD`, that assessment leaves the insult numerator without changing any cohort's membership.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — every lifecycle, posture, shift, staffing, resolution, challenge, transition and decision action — return `200 OK`, as do all reads. The logical-clock harness returns `200 OK`. Request and response shapes are not repeated here; they are established by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | PlatformAdmin |
| POST | `/fraud/customers` | Register a shopper account | PlatformAdmin, CheckoutService |
| GET | `/fraud/customers` | List shopper accounts | PlatformAdmin, CheckoutService, RiskAnalyst, ReviewLead, PolicyEngineer |
| GET | `/fraud/customers/{id}` | Read one shopper account | PlatformAdmin, CheckoutService, RiskAnalyst, ReviewLead, PolicyEngineer |
| POST | `/fraud/customers/{id}/posture` | Drive one customer posture axis | PlatformAdmin |
| POST | `/fraud/analysts` | Register a fraud analyst | PlatformAdmin |
| GET | `/fraud/analysts` | List the analyst roster | PlatformAdmin, ReviewLead, RiskAnalyst |
| GET | `/fraud/analysts/{id}` | Read one analyst | PlatformAdmin, ReviewLead, RiskAnalyst |
| POST | `/fraud/analysts/{id}/shift` | Move an analyst between shift states | PlatformAdmin |
| POST | `/fraud/devices` | Register a device fingerprint | CheckoutService, PlatformAdmin |
| GET | `/fraud/devices` | List device profiles | CheckoutService, PlatformAdmin, RiskAnalyst, ReviewLead, PolicyEngineer |
| GET | `/fraud/devices/{id}` | Read one device profile | CheckoutService, PlatformAdmin, RiskAnalyst, ReviewLead, PolicyEngineer |
| POST | `/fraud/addresses` | Register a shipping or billing address | CheckoutService, RiskAnalyst, PlatformAdmin |
| GET | `/fraud/addresses` | List address records | CheckoutService, RiskAnalyst, ReviewLead, PlatformAdmin, PolicyEngineer |
| GET | `/fraud/addresses/{id}` | Read one address record | CheckoutService, RiskAnalyst, ReviewLead, PlatformAdmin, PolicyEngineer |
| POST | `/fraud/rule-packs` | Draft a rule pack | PolicyEngineer |
| GET | `/fraud/rule-packs` | List rule packs | PolicyEngineer, ReviewLead, RiskAnalyst, PlatformAdmin |
| GET | `/fraud/rule-packs/{id}` | Read one rule pack | PolicyEngineer, ReviewLead, RiskAnalyst, PlatformAdmin |
| POST | `/fraud/rule-packs/{id}/activate` | Activate a draft rule pack | PolicyEngineer |
| GET | `/fraud/rule-packs/{id}/performance` | False-positive report for a rule pack | PolicyEngineer, ReviewLead |
| POST | `/fraud/rule-packs/{id}/rules` | Add a fraud rule to a draft pack | PolicyEngineer |
| GET | `/fraud/rule-packs/{id}/rules` | List a pack's rules in evaluation order | PolicyEngineer, ReviewLead, RiskAnalyst, PlatformAdmin |
| GET | `/fraud/rules/{id}` | Read one fraud rule | PolicyEngineer, ReviewLead, RiskAnalyst, PlatformAdmin |
| POST | `/fraud/risk-models` | Draft a scoring model | PolicyEngineer |
| GET | `/fraud/risk-models` | List scoring models | PolicyEngineer, ReviewLead, PlatformAdmin |
| GET | `/fraud/risk-models/{id}` | Read one scoring model | PolicyEngineer, ReviewLead, PlatformAdmin |
| POST | `/fraud/risk-models/{id}/lifecycle` | Drive the scoring-model lifecycle | PolicyEngineer |
| POST | `/fraud/checkout-assessments` | Open a checkout risk assessment | CheckoutService |
| GET | `/fraud/checkout-assessments` | List checkout assessments | CheckoutService, RiskAnalyst, ReviewLead, PolicyEngineer, PlatformAdmin |
| GET | `/fraud/checkout-assessments/{id}` | Read one checkout assessment | CheckoutService, RiskAnalyst, ReviewLead, PolicyEngineer, PlatformAdmin |
| POST | `/fraud/checkout-assessments/{id}/score` | Run the scoring pipeline and decide the assessment | CheckoutService |
| GET | `/fraud/review-cases` | List the manual-review queue | RiskAnalyst, ReviewLead, PlatformAdmin |
| GET | `/fraud/review-cases/{id}` | Read one review case | RiskAnalyst, ReviewLead, PlatformAdmin |
| POST | `/fraud/review-cases/{id}/assign` | Assign a case to a named analyst | ReviewLead |
| POST | `/fraud/review-cases/{id}/auto-assign` | Assign a case to the selector's chosen analyst | ReviewLead |
| POST | `/fraud/review-cases/{id}/resolve` | Approve, decline or escalate a case | RiskAnalyst, ReviewLead |
| POST | `/fraud/auth-events` | Record and score an authentication event | CheckoutService |
| GET | `/fraud/auth-events` | List authentication events | RiskAnalyst, ReviewLead, CheckoutService, PlatformAdmin |
| GET | `/fraud/auth-events/{id}` | Read one authentication event | RiskAnalyst, ReviewLead, CheckoutService, PlatformAdmin |
| POST | `/fraud/auth-events/{id}/challenge` | Drive the step-up challenge axis | CheckoutService |
| POST | `/fraud/chargebacks` | File a dispute against an approved order | PlatformAdmin |
| GET | `/fraud/chargebacks` | List disputes | PlatformAdmin, RiskAnalyst, ReviewLead, PolicyEngineer |
| GET | `/fraud/chargebacks/{id}` | Read one dispute | PlatformAdmin, RiskAnalyst, ReviewLead, PolicyEngineer |
| POST | `/fraud/chargebacks/{id}/transition` | Represent, win or lose a dispute | PlatformAdmin |
| POST | `/fraud/policy-exceptions` | Request a policy exception | RiskAnalyst |
| GET | `/fraud/policy-exceptions` | List policy exceptions | RiskAnalyst, ReviewLead, PlatformAdmin, CheckoutService |
| GET | `/fraud/policy-exceptions/{id}` | Read one policy exception | RiskAnalyst, ReviewLead, PlatformAdmin, CheckoutService |
| POST | `/fraud/policy-exceptions/{id}/decision` | Approve, reject or revoke a policy exception | ReviewLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_ROLE` | 401 |
| `ERR_INVALID_ROLE` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_USER_CONTEXT` | 401 |
| `ERR_NOT_CASE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ANALYST_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_ADDRESS_NOT_FOUND` | 404 |
| `ERR_RULE_PACK_NOT_FOUND` | 404 |
| `ERR_RULE_NOT_FOUND` | 404 |
| `ERR_RISK_MODEL_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_AUTH_EVENT_NOT_FOUND` | 404 |
| `ERR_CHARGEBACK_NOT_FOUND` | 404 |
| `ERR_EXCEPTION_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_ALREADY_SCORED` | 409 |
| `ERR_CUSTOMER_ACCOUNT_LOCKED` | 409 |
| `ERR_CUSTOMER_ATO_CONTAINED` | 409 |
| `ERR_CUSTOMER_POSTURE_INVALID` | 409 |
| `ERR_CASE_STATE_INVALID` | 409 |
| `ERR_CHARGEBACK_TRANSITION_INVALID` | 409 |
| `ERR_MODEL_TRANSITION_INVALID` | 409 |
| `ERR_RULE_PACK_NOT_DRAFT` | 409 |
| `ERR_EXCEPTION_STATE_INVALID` | 409 |
| `ERR_CHALLENGE_STATE_INVALID` | 409 |
| `ERR_CHALLENGE_EXPIRED` | 409 |
| `ERR_CHALLENGE_NOT_EXPIRED` | 409 |
| `ERR_STALE_ANALYST_VERSION` | 412 |
| `ERR_STALE_CUSTOMER_VERSION` | 412 |
| `ERR_ACTIVATION_SEGREGATION_VIOLATION` | 409 |
| `ERR_DECISION_SEGREGATION_VIOLATION` | 409 |
| `ERR_ESCALATION_SEGREGATION_VIOLATION` | 409 |
| `ERR_ESCALATED_REQUIRES_LEAD` | 422 |
| `ERR_ANALYST_SKILL_MISMATCH` | 422 |
| `ERR_ANALYST_NOT_AVAILABLE` | 409 |
| `ERR_RULE_PACK_NOT_ACTIVE` | 409 |
| `ERR_RISK_MODEL_NOT_ACTIVE` | 409 |
| `ERR_NO_ACTIVE_RULE_PACK` | 422 |
| `ERR_NO_ACTIVE_RISK_MODEL` | 422 |
| `ERR_EXCEPTION_SCOPE_ADDRESS_REQUIRED` | 422 |
| `ERR_EXCEPTION_ADDRESS_NOT_ALLOWED` | 422 |
| `ERR_ADDRESS_CLUSTER_DEPTH` | 422 |
| `ERR_CHARGEBACK_ASSESSMENT_NOT_APPROVED` | 422 |
| `ERR_RULE_FAMILY_MISMATCH` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_CHARGEBACK_BEFORE_DECISION` | 422 |
| `ERR_TRAINING_CUTOFF_IN_FUTURE` | 422 |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 |
| `ERR_RULE_PACK_WINDOW_OVERLAP` | 409 |
| `ERR_ANALYST_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_ELIGIBLE_ANALYST` | 422 |
| `ERR_RULE_PACK_EMPTY` | 422 |
| `ERR_EXCEPTION_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_DEVICE_HASH` | 409 |
| `ERR_DUPLICATE_RULE_CODE` | 409 |
| `ERR_CHALLENGE_ATTEMPTS_EXHAUSTED` | 409 |
| `ERR_TRAINING_SEGMENT_UNDERFILLED` | 422 |
| `ERR_WEIGHTS_NOT_NORMALIZED` | 422 |
| `ERR_INVALID_SCORE_BANDS` | 422 |
| `ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP` | 422 |
| `ERR_EXCEPTION_TIER_NOT_ELIGIBLE` | 422 |
| `ERR_CHARGEBACK_AMOUNT_EXCEEDS_ORDER` | 422 |
