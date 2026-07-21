# Public Adjuster & Claim Advocacy API — Product Requirements Document

## 1. Introduction

Public adjusters represent policyholders — not insurance carriers — in the documentation, valuation, and negotiation of first-party property-insurance claims. This API is the system of record for a public-adjusting firm's advocacy practice: it tracks the licensed adjusters and their state credentials, the clients they represent, the policies under which losses are claimed, the contingency-fee contracts that govern their engagement, and every claim from initial documentation through negotiation, appraisal, settlement, payment, and the final split of recovered funds between the firm, the client, and any prior cash advances.

The domain is adversarial and money-sensitive by nature. A carrier and a public adjuster exchange offers and counters until they either agree on a number or invoke a binding appraisal with a neutral umpire; the fee a client owes is a regulated fraction of what is actually recovered, capped by state statute; and the same policy coverage limit is a finite pool that every settlement and approved supplement draws down. Because the sums are large and the parties have opposing incentives, the system enforces strict separation of duties (the adjuster who accepts a settlement may not be the one who releases its funds), optimistic concurrency on claim revisions, and a licensing regime that ties every filing and activation to a valid state credential. This document specifies the complete contract an implementation must satisfy: the resource model, the state machines, the fee and exposure calculations, the validation ordering, and the REST surface.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. Business-process detail lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a value the server cannot validate, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the role is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles, spelled precisely: `PublicAdjuster`, `FirmPrincipal`, `Client`, `Carrier`, and `System`.

The meaning of `X-User-ID` depends on the role, and this binding is what enforces ownership:

- When `X-User-Role` is `PublicAdjuster`, `X-User-ID` is the `id` of the acting `Adjuster`; ownership checks on any resource that references an `Adjuster` compare the resource's adjuster foreign key to `X-User-ID`.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key to `X-User-ID`. In particular, only the client named on a contract may sign it: a sign request whose `X-User-ID` differs from the contract's `client_id` is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `FirmPrincipal`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `accepted_by_user_id` on a `Claim` when a principal accepts a settlement) but does not compare it to any entity's `id`.
- When `X-User-Role` is `Carrier`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `System`, `X-User-ID` is an opaque identifier for the automatic actor that performs cascaded transitions and drives the logical clock; it is not tied to any persisted entity.

Segregation of duties is layered on top of this binding: even when a role is authorized for an operation, the acting `X-User-ID` may be additionally constrained — see the disbursement-release rule in Section 2.9 and Section 3.7.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All of the resources in this system — `Adjuster`, `License`, `Client`, `Policy`, `Contract`, `Claim`, `Supplement`, `Appraisal`, `Payment`, `Disbursement`, and `Dispute` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on each mutation. The `version` field is the anchor for optimistic concurrency control (Section 2.8). Whenever a derived or computed field changes as a side effect of some operation — for example a policy's exposure figures being recomputed when a claim is filed — that counts as a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Monetary Values, Depreciation, and Rounding

All monetary amounts are integer cents; field names ending in `_cents` are always whole-cent integers, never fractional. Fractions used as multipliers — a contract's `fee_pct` and `statutory_cap_pct`, and a claim's `depreciation_pct` — are decimals (for example, `0.10` denotes ten percent) and preserve their input precision. Whenever a calculation multiplies an integer-cent amount by a fraction, the result is rounded to a whole number of cents using the round-half-up convention (a result whose fractional part is exactly one-half rounds away from zero, upward). This applies to actual-cash-value derivation, provisional and final fee assessment, and the disbursement fee split. Subtractions between already-rounded cent amounts are exact and are not re-rounded.

### 2.6. Cascading State Consistency

Many operations mutate more than one resource. When a settlement is accepted, an approved supplement is recorded, a payment clears, a contract is rescinded, or a claim is withdrawn, the system propagates the consequences across every dependent resource in the same logical transaction, and each affected resource independently has its `updated_at` refreshed and its `version` incremented. The server may also transition a resource automatically, without an explicit client request naming it: a claim advances itself to `PAID` once its recovery reaches its settlement, a contract advances itself to `COMPLETED` when a claim under it reaches `PAID`, and supplements and disbursements are voided automatically when their claim is unwound. The precise cascades are specified alongside the workflows that trigger them in Section 3; the governing principle is that no ledger figure, child state, or parent state is ever left inconsistent with the event that caused it.

### 2.7. Referenced-Resource Resolution

Endpoints identify resources both through path parameters (for example the `{id}` of a claim, supplement, or disbursement) and through foreign keys carried in request bodies (for example `policy_id`, `contract_id`, `claim_id`, `payment_id`, `adjuster_id`, `client_id`). The system validates the existence of every referenced resource before applying any business rule, resolving path identifiers left to right. The first identifier that does not correspond to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`; body-referenced resources are likewise checked for existence before state or business validation proceeds.

### 2.8. Optimistic Concurrency Control on Claim Revisions

Creating a supplement is the one write in this system that carries an optimistic-concurrency guard, because a supplement supersedes the client's prior view of the claim's settlement and draws down the policy's finite remaining limit. A create-supplement request must include `expected_claim_version`, a non-optional field carrying the client's last observed `version` of the target `Claim`. If that value does not equal the claim's current `version` — meaning another writer has advanced the claim since the client last read it — the create is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), preventing the writer from stacking a supplement on an outdated view of the available headroom. When the versions match, the supplement is created and the claim's `version` is incremented by one as part of the write. No other endpoint accepts or requires a client-supplied version field.

### 2.9. Licensing, Policy Exposure, and Segregation of Duties

Three cross-cutting business principles recur across the workflows and are stated once here.

**Licensing.** A `License` authorizes a specific `Adjuster` to practice in a specific two-letter `state_code` over an inclusive validity interval bounded by `effective_date` and `expiry_date`. A license is currently valid only when its `status` is `ACTIVE` and the logical clock falls on or after `effective_date` and on or before `expiry_date`. Two operations require a currently-valid license in the loss state: filing a claim and activating a contract. In both, the absence of an `ACTIVE` license whose `state_code` matches the relevant loss state and whose validity interval contains the current clock instant is rejected with `ERR_LICENSE_NOT_VALID`. When a new license is issued, its validity interval must not overlap the interval of any existing non-`REVOKED` license held by the same adjuster in the same state; an overlap is rejected with `ERR_LICENSE_PERIOD_OVERLAP`.

**Policy exposure (dual view).** Each `Policy` exposes two independently computed exposure figures against its `coverage_limit_cents`. The forward-looking figure, `forward_exposure_cents`, is the sum of `pa_acv_estimate_cents` over every claim on the policy whose `status` is neither `PAID` nor `WITHDRAWN` — a reserve view across all still-open claims. The booked figure, `committed_cents`, counts only realized commitments: the sum of `settlement_amount_cents` over claims whose `status` is `SETTLED` or `PAID`, plus the sum of `amount_cents` over supplements on the policy whose `status` is `APPROVED`. The policy's `remaining_limit_cents` is `coverage_limit_cents` minus `committed_cents`, and the invariant `coverage_limit_cents == remaining_limit_cents + committed_cents` holds at all times. Both figures are recomputed whenever a claim is filed, withdrawn, or settled and whenever a payment clears.

**Segregation of duties.** The user who accepts a settlement is recorded on the claim as `accepted_by_user_id`. When funds are later released to the client, the releasing user's `X-User-ID` must differ from that recorded acceptor; a release attempted by the same user is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) role authorization, including the ownership check for entity-backed roles (`ERR_FORBIDDEN`); (3) existence of every path- and body-referenced resource, checked left to right (`ERR_NOT_FOUND`); (4) the target resource being in a state from which the requested transition is legal, which includes the requirement that a claim be settled before a supplement may be created against it (`ERR_INVALID_STATE`); (5) licensing validity for claim filing and contract activation (`ERR_LICENSE_NOT_VALID`); (6) referential status — the referenced contract and policy being active when a claim is filed (`ERR_CONTRACT_NOT_ACTIVE`, `ERR_POLICY_NOT_ACTIVE`); (7) temporal-window checks such as loss-within-policy-period, supplement window, rescission window, and inspection non-overlap (`ERR_LOSS_OUTSIDE_POLICY_PERIOD`, `ERR_SUPPLEMENT_WINDOW_CLOSED`, `ERR_RESCISSION_WINDOW_CLOSED`, `ERR_INSPECTION_OVERLAP`); (8) distinctness and range constraints such as license-interval non-overlap, appraiser/umpire distinctness, umpire-award range, and the statutory fee cap at contract creation (`ERR_LICENSE_PERIOD_OVERLAP`, `ERR_APPRAISER_CONFLICT`, `ERR_AWARD_OUT_OF_RANGE`, `ERR_FEE_EXCEEDS_STATUTORY_CAP`); (9) segregation of duties on disbursement release (`ERR_SEGREGATION_OF_DUTIES`); (10) fiscal capacity — a supplement or settlement amount fitting within the policy remaining limit (`ERR_POLICY_LIMIT_EXCEEDED`); (11) the optimistic-concurrency check on supplement creation (`ERR_STALE_CLAIM_VERSION`); and (12) body well-formedness — required fields present, amounts non-negative, enums valid (`ERR_VALIDATION`). Earlier checks take precedence, so a failure at an earlier priority masks any later failure on the same request.

### 2.11. The Logical Clock

Time in this system is a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-07-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. An administrative test-driving capability sets the clock to a supplied instant by accepting a `to_iso8601` value; every timestamp the system records — a contract's `signed_at`, a supplement's `submitted_at`, a payment's `received_at`, a claim's `settled_at`, a disbursement's `released_at` — is drawn from this clock at the moment of the operation, and every window and validity-interval comparison is made against it.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Adjusters, Licensing, Clients, and Policies

A `FirmPrincipal` onboards a public adjuster by creating an `Adjuster` with a `full_name`, a `firm_name`, and an `email`. Adjusters are always in `ACTIVE` `status` in this system. Each adjuster is a real user: an operator acting as `PublicAdjuster` presents the adjuster's `id` as their `X-User-ID`.

Licensing is managed entirely by the principal. Issuing a `License` names the holding adjuster through `adjuster_id`, the authorized two-letter `state_code`, the `license_number`, and the inclusive `effective_date`/`expiry_date` interval; a freshly issued license starts `ACTIVE`. Because a license may not overlap another live credential for the same adjuster and state, issuance is rejected with `ERR_LICENSE_PERIOD_OVERLAP` when the new interval overlaps any existing non-`REVOKED` license for that `(adjuster_id, state_code)` pair. A license moves through `ACTIVE`, `SUSPENDED`, and `REVOKED`: suspending an active license drives its `status` to `SUSPENDED`, reinstating a suspended one returns it to `ACTIVE`, and revoking from either `ACTIVE` or `SUSPENDED` drives it to the terminal `REVOKED`. Licenses can be listed and filtered by `adjuster_id`, `state_code`, or `status` so that a claim or contract flow can confirm a credential before it proceeds.

Clients and policies are created by either a `FirmPrincipal` or a `PublicAdjuster`. A `Client` records the policyholder's `full_name`, `email`, and two-letter `mailing_state`, and is always `ACTIVE`. A `Policy` belongs to a client through `client_id` and records the `carrier_name`, `policy_number`, the `policy_type` (one of `HO3`, `HO5`, `COMMERCIAL`, or `FLOOD`), the `coverage_limit_cents` that forms the finite allocation pool, the per-claim `deductible_cents`, and the inclusive coverage period bounded by `effective_date` and `expiry_date`. A new policy starts `ACTIVE` with `committed_cents` at 0 and `remaining_limit_cents` equal to the full `coverage_limit_cents`; its `forward_exposure_cents` likewise starts at 0. A policy may be driven to the terminal `LAPSED` or `CANCELLED` states by either a `FirmPrincipal` or a `Carrier`. Policies can be listed and filtered by `client_id` or `status`.

### 3.2. The Representation Contract

Before any claim can be worked, the firm and the client execute a contingency-fee `Contract`. A `FirmPrincipal` drafts it, naming the represented `client_id`, the retained `adjuster_id`, the two-letter `loss_state_code` that governs licensing and the statutory cap, the contingency `fee_pct` expressed as a fraction of recovery, the governing `statutory_cap_pct`, and optionally a `prior_advance_cents` figure recording cash already advanced to the client (defaulting to 0 when omitted). At creation the fee must not exceed the statutory ceiling: a contract whose `fee_pct` is greater than its `statutory_cap_pct` is rejected with `ERR_FEE_EXCEEDS_STATUTORY_CAP`, while equality is accepted. A new contract begins in `DRAFT`, and the system also seeds its `advance_recouped_cents` at 0; the outstanding advance at any moment is `prior_advance_cents` minus `advance_recouped_cents`.

The contract advances through `DRAFT`, `SIGNED`, `ACTIVE`, and the terminal `RESCINDED`, `COMPLETED`, and `CANCELLED`. Signing is reserved to the represented client: the operation is authorized only for the `Client` role, and the acting client's `X-User-ID` must equal the contract's `client_id`, otherwise it is rejected with `ERR_FORBIDDEN`. Signing moves the contract from `DRAFT` to `SIGNED`, stamps `signed_at` with the current clock instant, and sets `rescission_deadline_at` to `signed_at` advanced by the cooling-off period, a fixed number of days denoted `RESCISSION_WINDOW_DAYS`, which equals 3 days. Activation, performed by a `FirmPrincipal`, moves the contract from `SIGNED` to `ACTIVE` but only if the retained adjuster holds a currently-valid `ACTIVE` license in the contract's `loss_state_code` at the current clock instant; otherwise it is rejected with `ERR_LICENSE_NOT_VALID`.

A cooling-off rescission may be initiated by either the `Client` or a `FirmPrincipal` from either the `SIGNED` or the `ACTIVE` state, provided the current clock instant is on or before `rescission_deadline_at`; a later attempt is rejected with `ERR_RESCISSION_WINDOW_CLOSED`. Rescission moves the contract to the terminal `RESCINDED` and triggers a two-link cascade. First, every non-terminal claim on the contract — any claim in `FILED`, `NEGOTIATING`, `OFFER_RECEIVED`, `IN_APPRAISAL`, or `SETTLED` — is driven to `WITHDRAWN`, and any settlement that had been committed for a `SETTLED` claim is released from the policy's `committed_cents` with `remaining_limit_cents` recomputed, while the policy's `forward_exposure_cents` is recomputed as those claims leave the open set. If a withdrawn claim was `IN_APPRAISAL`, any `INVOKED` appraisal on it is driven to the terminal `CANCELLED` as part of the same cascade. Second, as each such claim is withdrawn, its own supplements in `DRAFT` or `SUBMITTED` are driven to the terminal `VOIDED`.

A contract may also be cancelled by a `FirmPrincipal`. Cancellation from `DRAFT` is unconditional and drives the contract to the terminal `CANCELLED`. Cancellation from `SIGNED` is permitted only when no non-terminal claim exists on the contract; otherwise it is rejected with `ERR_INVALID_STATE`. Finally, the contract reaches the terminal `COMPLETED` automatically — driven by the `System` actor — when a claim under it reaches `PAID`. Contracts can be listed and filtered by `client_id`, `adjuster_id`, or `status`.

### 3.3. Filing and Documenting a Claim

A `PublicAdjuster` opens a `Claim` against a specific policy and contract, supplying `policy_id`, `contract_id`, the `date_of_loss`, the two-letter `loss_state_code`, the `peril_type` (one of `WIND`, `WATER`, `FIRE`, `HAIL`, or `THEFT`), the documented replacement-cost estimate `pa_rcv_estimate_cents`, and the `depreciation_pct` fraction that will be applied to derive actual cash value. A newly created claim starts in `DRAFT` with `version` 1. Its negotiation and accounting fields begin at their defaults: `carrier_offer_cents`, `pa_counter_cents`, `negotiation_round`, `settlement_amount_cents`, `amount_recovered_cents`, `provisional_fee_cents`, and `final_fee_cents` all start at 0.

Filing the claim with the carrier moves it from `DRAFT` to `FILED` and is subject to four preconditions in the order the system evaluates them: the referenced contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`); the referenced policy must be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`); the retained adjuster must hold a currently-valid license in the claim's `loss_state_code` at the current clock instant (else `ERR_LICENSE_NOT_VALID`); and the `date_of_loss` must fall on or after the policy's `effective_date` and on or before its `expiry_date` (else `ERR_LOSS_OUTSIDE_POLICY_PERIOD`). On a successful file, the system computes the actual-cash-value estimate `pa_acv_estimate_cents` as the replacement-cost estimate multiplied by one minus the depreciation fraction, rounded half up to whole cents; because the claim is now open, the policy's `forward_exposure_cents` is recomputed to include this claim's ACV estimate.

Before or during negotiation the adjuster schedules the physical damage inspection, supplying an `inspection_start` and an `inspection_end` (the end being exclusive of the window). A scheduled window may not sit too close to another inspection already booked for the same adjuster: if the new window falls within a fixed buffer — denoted `TRAVEL_BUFFER_MINUTES`, which equals 60 minutes — of another of that adjuster's inspections, it is rejected with `ERR_INSPECTION_OVERLAP`. Claims can be listed and filtered by `policy_id`, `contract_id`, or `status`, and a single claim's response exposes its `version` (for concurrency control) alongside its computed fee fields.

### 3.4. Negotiation and Settlement

Once a claim is `FILED`, the carrier and the public adjuster exchange positions in a cyclic negotiation. The carrier records a settlement offer by supplying `offer_cents`; this drives the claim to `OFFER_RECEIVED`, stores the amount in `carrier_offer_cents`, and increments `negotiation_round` by one. From `OFFER_RECEIVED` the public adjuster may counter by supplying `counter_cents`, which drives the claim to `NEGOTIATING`, stores the amount in `pa_counter_cents`, and again increments `negotiation_round`. From `NEGOTIATING` the carrier may record a fresh offer, returning the claim to `OFFER_RECEIVED` and incrementing the round once more; the pair `OFFER_RECEIVED` and `NEGOTIATING` may cycle across as many rounds as the parties need.

From `OFFER_RECEIVED`, the public adjuster may accept the standing offer, driving the claim to `SETTLED`. Acceptance sets `settlement_amount_cents` to the current `carrier_offer_cents`, stamps `settled_at` with the current clock instant, records the accepting operator's `X-User-ID` in `accepted_by_user_id` (the datum that later drives segregation of duties), and computes the provisional fee. The provisional fee, `provisional_fee_cents`, is the effective fee rate multiplied by the claim's `pa_acv_estimate_cents`, rounded half up to whole cents, where the effective rate is the smaller of the contract's `fee_pct` and its `statutory_cap_pct`. Acceptance also books the settlement against the policy: `committed_cents` increases by `settlement_amount_cents`, and `remaining_limit_cents` is recomputed. The `settled_at` instant anchors the window within which supplements may later be submitted.

A claim that has not yet settled can be withdrawn at any point in `FILED`, `NEGOTIATING`, or `OFFER_RECEIVED` by either the `PublicAdjuster` or a `FirmPrincipal`, driving it to the terminal `WITHDRAWN` and recomputing the policy's `forward_exposure_cents` as the claim leaves the open set. Withdrawal from later states occurs only as an automatic consequence of a contract rescission, described in Section 3.2 and Section 3.6.

### 3.5. Appraisal and Umpire

When the carrier and the adjuster cannot agree, either a `PublicAdjuster` or a `FirmPrincipal` may invoke a binding appraisal by naming the disputed `claim_id`. Invocation is allowed only when a carrier offer is already on record — that is, when the claim is in `OFFER_RECEIVED` or `NEGOTIATING`; an attempt from any other state is rejected with `ERR_INVALID_STATE`. Invocation creates an `Appraisal` in `INVOKED` and drives the parent claim to `IN_APPRAISAL`.

Naming the appraisers records both sides' experts and their valuations: `pa_appraiser_name` with `pa_appraiser_amount_cents`, and `carrier_appraiser_name` with `carrier_appraiser_amount_cents`. The two appraisers must be distinct people: if `pa_appraiser_name` equals `carrier_appraiser_name`, the request is rejected with `ERR_APPRAISER_CONFLICT`. A successful naming moves the appraisal from `INVOKED` to `APPRAISERS_NAMED`.

From `APPRAISERS_NAMED` the outcome forks on whether the two appraiser valuations agree. When the two amounts are equal, the award may be rendered directly: rendering drives the appraisal to the terminal `AWARDED`, sets `award_cents` equal to `pa_appraiser_amount_cents`, and cascades the parent claim from `IN_APPRAISAL` to `SETTLED` with no umpire involved. Attempting this agree-branch render while the two appraiser amounts differ is rejected with `ERR_UMPIRE_REQUIRED`. When the amounts differ, a neutral umpire must first be selected by supplying `umpire_name`; selection is rejected with `ERR_UMPIRE_NOT_NEEDED` if the two appraiser amounts are in fact equal, and with `ERR_APPRAISER_CONFLICT` if the proposed `umpire_name` duplicates either appraiser's name. Selecting an umpire moves the appraisal to `UMPIRE_SELECTED`. From there the award is rendered with a supplied `award_cents`, which must lie within the inclusive range bounded by the smaller and the larger of the two appraiser valuations; an award below the minimum or above the maximum of `pa_appraiser_amount_cents` and `carrier_appraiser_amount_cents` is rejected with `ERR_AWARD_OUT_OF_RANGE`. A valid umpire-branch render drives the appraisal to `AWARDED`, records the supplied `award_cents`, and cascades the parent claim from `IN_APPRAISAL` to `SETTLED`.

When the claim settles by appraisal award, the same settlement side effects apply as for a negotiated acceptance: `settlement_amount_cents` is set to the award, `settled_at` is stamped, `accepted_by_user_id` records the `X-User-ID` that rendered the award, `provisional_fee_cents` is computed as the effective rate times `pa_acv_estimate_cents` rounded half up, and the policy's `committed_cents` and `remaining_limit_cents` are updated. An appraisal that is still `INVOKED` may instead be cancelled by a `PublicAdjuster` or `FirmPrincipal`, driving the appraisal to the terminal `CANCELLED` and returning the parent claim from `IN_APPRAISAL` back to `NEGOTIATING`. Appraisals can be listed and filtered by `claim_id` or `status`.

### 3.6. Supplements

A supplement captures additional loss discovered after a claim has settled — hidden damage, for instance. Creating a `Supplement` is reserved to the `PublicAdjuster` and names the settled `claim_id`, the additional `amount_cents`, a free-text `reason`, and the concurrency guard `expected_claim_version`. The target claim must already be `SETTLED` or `PAID`; a create against a claim that has not settled is rejected with `ERR_INVALID_STATE`. The supplied `expected_claim_version` must match the claim's current `version`, or the create is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412) as described in Section 2.8; a successful create starts the supplement in `DRAFT` and increments the claim's `version` by one. Supplements can be listed and filtered by `claim_id` or `status`.

Submitting a supplement to the carrier moves it from `DRAFT` to `SUBMITTED` and stamps `submitted_at` with the current clock instant, but only within the supplement window: the number of days between the claim's settlement instant and the current clock instant must be at most `SUPPLEMENT_WINDOW_DAYS`, which equals 365 days, otherwise the submission is rejected with `ERR_SUPPLEMENT_WINDOW_CLOSED`.

A `FirmPrincipal` records the carrier's decision on a submitted supplement by supplying a `decision`. On an approve decision, the additional amount must fit within the policy's current headroom: if `amount_cents` exceeds the policy's `remaining_limit_cents`, the decision is rejected with `ERR_POLICY_LIMIT_EXCEEDED`; otherwise the supplement moves to the terminal `APPROVED`, the policy's `committed_cents` increases by `amount_cents` with `remaining_limit_cents` recomputed, and the claim's `settlement_amount_cents` increases by the same amount. On a deny decision the supplement moves to the terminal `DENIED` with no ledger change. Supplements in `DRAFT` or `SUBMITTED` are driven to the terminal `VOIDED` automatically when their claim is withdrawn or their contract is rescinded.

### 3.7. Payments, the Disbursement Waterfall, and Release

The carrier records money against a settled claim as a `Payment`, supplying the `claim_id`, the `amount_cents`, and the `payment_type` (one of `INITIAL`, `SUPPLEMENT`, or `APPRAISAL_AWARD`). A new payment starts in `RECEIVED`. Clearing a payment, performed by the carrier, requires that the claim be `SETTLED` or `PAID`; a clear against any other claim state is rejected with `ERR_CLAIM_NOT_SETTLED`. Clearing stamps `received_at`, moves the payment to `CLEARED`, adds its `amount_cents` to the claim's `amount_recovered_cents`, and triggers a cascade: a `Disbursement` is created in `PENDING` to split this payment, and if the claim's cumulative `amount_recovered_cents` has reached or exceeded its `settlement_amount_cents`, the claim advances from `SETTLED` to the terminal `PAID`. When the claim reaches `PAID`, the final fee is recomputed, the contract advances to `COMPLETED`, and the policy's booked exposure is reconciled to the amount actually recovered.

The disbursement splits the cleared payment three ways. The gross amount, `gross_cents`, equals the cleared payment's `amount_cents`. The firm's fee, `fee_cents`, is the effective fee rate — the smaller of the contract's `fee_pct` and `statutory_cap_pct` — multiplied by `gross_cents`, rounded half up to whole cents. The advance recoupment, `advance_recoup_cents`, is the smaller of two quantities: the gross net of fee (that is, `gross_cents` minus `fee_cents`), and the contract's outstanding advance (that is, `prior_advance_cents` minus `advance_recouped_cents` at the moment of the split). The client's share, `client_cents`, is `gross_cents` minus `fee_cents` minus `advance_recoup_cents`.

The final fee differs from the provisional fee in both base and rounding discipline. Whereas the provisional fee was computed once against the ACV estimate, the final fee, `final_fee_cents`, is computed over actual recovery: for each `CLEARED` payment on the claim, the effective rate times that payment's `amount_cents` is rounded half up to whole cents, and those per-payment rounded fees are then summed. The order is fixed — each payment's fee is rounded first and the rounded results are summed — rather than rounding a single product of the rate and the aggregate of payment amounts; the two can differ by up to a cent. The final fee is recomputed on each payment clear and when the claim reaches `PAID`.

Releasing a disbursement pays the client their share and is performed by a `PublicAdjuster` or a `FirmPrincipal` on a `PENDING` disbursement. Two guards apply. First, segregation of duties: the releasing user's `X-User-ID` must not equal the claim's `accepted_by_user_id`, or the release is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, no open dispute may exist: if any dispute on the claim is `OPEN` or `UNDER_REVIEW`, the release is rejected with `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`. A successful release drives the disbursement to the terminal `RELEASED`, stamps `released_at`, and adds this disbursement's `advance_recoup_cents` to the contract's `advance_recouped_cents`. A pending disbursement may instead be held (moving `PENDING` to `HELD`) and later resumed (moving `HELD` back to `PENDING`) by a `PublicAdjuster` or `FirmPrincipal`; hold and resume may cycle.

A cleared payment may be reversed by a `Carrier` or a `FirmPrincipal` as a compensating action, but only while the disbursement that split it has not yet been released: a reverse attempted after that disbursement is `RELEASED` is rejected with `ERR_DISBURSEMENT_RELEASED`. Reversal moves the payment from `CLEARED` to the terminal `REVERSED`, subtracts its `amount_cents` back out of the claim's `amount_recovered_cents`, drives the splitting disbursement to the terminal `VOIDED`, and restores the contract's `advance_recouped_cents` by that disbursement's `advance_recoup_cents`. A disbursement that is `PENDING` or `HELD` when its payment is reversed is the one voided by this cascade. Disbursements are never created directly; they are discovered through retrieval and can be listed and filtered by `claim_id`, `payment_id`, or `status`.

### 3.8. Disputes

Any of a `Client`, a `Carrier`, or a `FirmPrincipal` may raise a `Dispute` on a claim, naming the `claim_id`, the `dispute_type` (one of `FEE`, `SERVICE`, or `LICENSING`), the party in `raised_by` (either `CLIENT` or `CARRIER`), and a free-text `description`. A new dispute starts `OPEN`. A `FirmPrincipal` begins review, moving it from `OPEN` to `UNDER_REVIEW`, and resolves it, moving it from `UNDER_REVIEW` to the terminal `RESOLVED` while recording a `resolution` note. Either the `Client` or the `Carrier` may withdraw a dispute from `OPEN` or `UNDER_REVIEW`, driving it to the terminal `WITHDRAWN`. While a dispute on a claim remains `OPEN` or `UNDER_REVIEW`, it blocks release of that claim's disbursements as described in Section 3.7. Disputes can be listed and filtered by `claim_id` or `status`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. The logical-clock endpoint returns `200 OK`. Full request and response semantics for each endpoint are reconstructed from the workflow narratives in Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock | FirmPrincipal, System, PublicAdjuster, Carrier |
| POST | `/v1/adjusters` | Create an Adjuster | FirmPrincipal |
| GET | `/v1/adjusters/{id}` | Get an Adjuster | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/licenses` | Issue a License to an Adjuster | FirmPrincipal |
| GET | `/v1/licenses/{id}` | Get a License | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/licenses` | List Licenses | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/licenses/{id}/suspend` | Suspend a License | FirmPrincipal |
| POST | `/v1/licenses/{id}/reinstate` | Reinstate a suspended License | FirmPrincipal |
| POST | `/v1/licenses/{id}/revoke` | Revoke a License | FirmPrincipal |
| POST | `/v1/clients` | Create a Client | FirmPrincipal, PublicAdjuster |
| GET | `/v1/clients/{id}` | Get a Client | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/policies` | Create a Policy | FirmPrincipal, PublicAdjuster |
| GET | `/v1/policies/{id}` | Get a Policy | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/policies` | List Policies | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/policies/{id}/lapse` | Mark a Policy LAPSED | FirmPrincipal, Carrier |
| POST | `/v1/policies/{id}/cancel` | Cancel a Policy | FirmPrincipal, Carrier |
| POST | `/v1/contracts` | Create a representation Contract | FirmPrincipal |
| GET | `/v1/contracts/{id}` | Get a Contract | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/contracts` | List Contracts | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/contracts/{id}/sign` | Client signs the Contract | Client |
| POST | `/v1/contracts/{id}/activate` | Activate a signed Contract | FirmPrincipal |
| POST | `/v1/contracts/{id}/rescind` | Rescind within the cooling-off window | Client, FirmPrincipal |
| POST | `/v1/contracts/{id}/cancel` | Cancel a Contract | FirmPrincipal |
| POST | `/v1/claims` | Create a Claim | PublicAdjuster |
| GET | `/v1/claims/{id}` | Get a Claim | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/claims` | List Claims | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/claims/{id}/file` | File the claim with the carrier | PublicAdjuster |
| POST | `/v1/claims/{id}/schedule-inspection` | Schedule the damage inspection window | PublicAdjuster |
| POST | `/v1/claims/{id}/record-offer` | Carrier records a settlement offer | Carrier |
| POST | `/v1/claims/{id}/counter` | Public adjuster counters | PublicAdjuster |
| POST | `/v1/claims/{id}/accept-settlement` | Accept the current carrier offer | PublicAdjuster |
| POST | `/v1/claims/{id}/withdraw` | Withdraw the claim | PublicAdjuster, FirmPrincipal |
| POST | `/v1/supplements` | Create a Supplement (OCC on Claim.version) | PublicAdjuster |
| GET | `/v1/supplements/{id}` | Get a Supplement | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/supplements` | List Supplements | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/supplements/{id}/submit` | Submit a supplement to the carrier | PublicAdjuster |
| POST | `/v1/supplements/{id}/decide` | Firm records the carrier decision | FirmPrincipal |
| POST | `/v1/appraisals` | Invoke appraisal on a claim | PublicAdjuster, FirmPrincipal |
| GET | `/v1/appraisals/{id}` | Get an Appraisal | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/appraisals` | List Appraisals | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/appraisals/{id}/name-appraisers` | Name both appraisers and their valuations | PublicAdjuster, FirmPrincipal |
| POST | `/v1/appraisals/{id}/select-umpire` | Select a neutral umpire when appraisers disagree | PublicAdjuster, FirmPrincipal |
| POST | `/v1/appraisals/{id}/render-award` | Render the binding award | PublicAdjuster, FirmPrincipal, System |
| POST | `/v1/appraisals/{id}/cancel` | Cancel an invoked appraisal | PublicAdjuster, FirmPrincipal |
| POST | `/v1/payments` | Carrier records a payment on the claim | Carrier |
| GET | `/v1/payments/{id}` | Get a Payment | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/payments` | List Payments | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/payments/{id}/clear` | Clear a payment; may drive the claim to PAID | Carrier |
| POST | `/v1/payments/{id}/reverse` | Reverse a cleared payment | Carrier, FirmPrincipal |
| GET | `/v1/disbursements/{id}` | Get a Disbursement | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/disbursements` | List Disbursements | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/disbursements/{id}/release` | Release funds to the client | PublicAdjuster, FirmPrincipal |
| POST | `/v1/disbursements/{id}/hold` | Hold a pending disbursement | PublicAdjuster, FirmPrincipal |
| POST | `/v1/disbursements/{id}/resume` | Resume a held disbursement | PublicAdjuster, FirmPrincipal |
| POST | `/v1/disputes` | Raise a Dispute on a claim | Client, Carrier, FirmPrincipal |
| GET | `/v1/disputes/{id}` | Get a Dispute | FirmPrincipal, PublicAdjuster, Client, Carrier |
| GET | `/v1/disputes` | List Disputes | FirmPrincipal, PublicAdjuster, Client, Carrier |
| POST | `/v1/disputes/{id}/review` | Begin review of a dispute | FirmPrincipal |
| POST | `/v1/disputes/{id}/resolve` | Resolve a dispute | FirmPrincipal |
| POST | `/v1/disputes/{id}/withdraw` | Withdraw a dispute | Client, Carrier |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LICENSE_NOT_VALID` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_POLICY_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOSS_OUTSIDE_POLICY_PERIOD` | 409 Conflict |
| `ERR_SUPPLEMENT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RESCISSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_INSPECTION_OVERLAP` | 409 Conflict |
| `ERR_LICENSE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_APPRAISER_CONFLICT` | 409 Conflict |
| `ERR_UMPIRE_NOT_NEEDED` | 409 Conflict |
| `ERR_UMPIRE_REQUIRED` | 409 Conflict |
| `ERR_AWARD_OUT_OF_RANGE` | 409 Conflict |
| `ERR_FEE_EXCEEDS_STATUTORY_CAP` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_OPEN_DISPUTE_BLOCKS_RELEASE` | 409 Conflict |
| `ERR_DISBURSEMENT_RELEASED` | 409 Conflict |
| `ERR_CLAIM_NOT_SETTLED` | 409 Conflict |
| `ERR_POLICY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_STALE_CLAIM_VERSION` | 412 Precondition Failed |
