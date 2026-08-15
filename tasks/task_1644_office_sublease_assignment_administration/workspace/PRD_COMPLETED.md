# Office Sublease & Assignment Administration API — Product Requirements Document

## 1. Introduction

Commercial office leases rarely let a tenant hand off space freely. A typical lease conditions any sublease or assignment on a minimum marketing effort, a creditworthy incoming counterparty, the landlord's written consent within a fixed number of business days, and a negotiated split of any profit the tenant captures above its own pass-through rent. Administered on paper, these provisions breed disputes: consent windows miscounted over weekends, the same broker both marketing the space and vouching for the subtenant's credit, and profit-share checks that nobody can recompute. This document specifies an API that administers the entire transfer-consent lifecycle programmatically for tenant-representation brokerages, landlords, tenants, and the prospective subtenants and assignees who countersign the closing papers.

The surface distinguishes the two transfer flavors the market recognizes. A `SUBLEASE` keeps the original tenant in privity with the landlord and retains its liability; an `ASSIGNMENT` novates the lease and may release the assignor when the landlord so elects at consent time. Around that distinction the API orchestrates space measurement under competing measurement standards, a segregation-of-duties credit attestation, an express consent decision that may carry conditions and may be rescinded, a deemed-approval reminder timer driven by a logical clock, execution and recognition of the closing instruments, tiered profit-sharing settlements reconciled against a lease ledger, and restoration obligations tracked through the end of the transfer's life. All endpoints are mounted under the `/sublease-admin` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: who may call what, what responses look like, how time and money are represented, and the order in which the server evaluates competing rejection reasons.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request whose headers are missing or malformed, or whose role is not one of the six recognized role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose role is not on the invoked endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles are `AssetManager`, `TenantRepBroker`, `Landlord`, `Tenant`, `Subtenant`, and `Assignee`. Their identity semantics differ, and the distinction is load-bearing:

- When `X-User-Role` is `AssetManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `TenantRepBroker`, `X-User-ID` is likewise opaque. The server records it — as `broker_user_id` on the transfer the broker originates and as `attesting_broker_user_id` on the credit review the broker attests — and compares those two recorded values against each other to enforce segregation of duties; it never compares a broker's identifier to a `Party` `id`.
- When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Party`; ownership checks compare the lease's `landlord_party_id` to `X-User-ID`.
- When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Party`, compared to the lease's `tenant_party_id`.
- When `X-User-Role` is `Subtenant` or `Assignee`, `X-User-ID` is the `id` of the acting `Party`, compared to the transfer's `counterparty_id` when that party countersigns a recognition agreement.

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

Requests to an undefined path, and requests to a defined path with a method it does not support, are rejected in this same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, and a supplied value is clamped into the accepted range of 1 to 100 rather than rejected, with a non-integer value falling back to the default. The `offset` parameter skips a number of items before returning the page: it defaults to 0, is raised to 0 when negative, and falls back to the default when non-integer. Every list response — paginated or not — carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless otherwise specified, list endpoints sort by `created_at` in ascending order.

### 2.4. Common Resource Properties

Every resource in this domain — parties, buildings, leases, measurements, transfers, consent reviews, consent conditions, credit reviews, instruments, recognition agreements, settlements, and restoration obligations — carries a uniform set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation.

A mutation is anything that changes the stored representation: explicit client writes, system cascades that flip a status or set a timestamp, and recomputation of a derived field all count, each refreshing `updated_at` and incrementing `version` on every resource the write touches. When one operation mutates several resources — consent granting that also advances the transfer, finalization that also debits the lease ledger — each affected resource is updated independently.

### 2.5. The Logical Clock and the Business-Day Calendar

Every timestamp a workflow consults — submissions, deadlines, decisions, signatures, reminders, executions, finalizations — is stamped from a server-side logical clock, never from wall-clock time; only audit metadata runs on wall time, namely the envelope's `api_request_timestamp` and each resource's `created_at` and `updated_at`. At startup the logical clock reads exactly 2026-08-01T00:00:00.000Z, which is a Saturday; the server must not fall back to wall-clock time under any circumstance. An `AssetManager` drives the clock forward through an admin-only test capability that accepts a `to_iso8601` instant; the supplied instant is adopted verbatim, with no monotonicity check against the previous reading, an offset-less value read as UTC, and an unparseable value rejected with `ERR_INVALID_REQUEST` (HTTP 400); the response reports the resulting `current_utc` and an `advanced_transitions` count of how many automatic transitions the advance fired. Advancing the clock is what evaluates the deemed-approval machinery described in §3.6 for every transfer sitting in `SUBMITTED` or `CONSENT_PENDING`.

Consent windows are counted in business days. Business days are Monday through Friday; Saturdays and Sundays are skipped, and there is no holiday calendar. A business day ends at exactly 17:00:00.000Z, and every deadline in this domain lands at that instant on its final counted day. Timestamps throughout are exact to milliseconds.

### 2.6. Measurement Standards, Monetary Units, and Rounding Discipline

Three numeric disciplines run through the domain. Square footages are integers; usable and rentable areas are never fractional. Monetary amounts are integer cents — rents are quoted as annual cents per rentable square foot, and settlements compute in whole cents. Ratios are integer basis points on a ten-thousand-point scale: credit ratings run from 0 to 10000, building loss factors from 0 to 5000, and profit-share percentages from 0 to 10000.

Whenever a calculation discards a fraction — deriving rentable square feet, pro-rata shares, annualized profit, or a tier's landlord share — it rounds half-up to the nearest integer. Where a formula rounds more than once, the rounding steps are pinned in a fixed order and each step rounds its own intermediate result before the next step consumes it; §3.3 and §3.8 state each formula's pinned order. Reordering or fusing those steps is a specification violation, because nested rounding produces different cents.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both take their version field as a non-optional input.

Creating a transfer request against a lease (`POST /sublease-admin/leases/{lease_id}/transfer-requests`) requires the client to supply `expected_lease_version`, carrying the lease `version` the client last observed. If the lease's current `version` has advanced since that observation — because another writer submitted or withdrew a transfer, originated one, or finalized a settlement, each of which legitimately moves the lease's version — the create is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412), so the client cannot originate a transfer from a stale view of the lease.

Submitting a landlord consent decision (`POST /sublease-admin/consent-reviews/{id}/decide`) requires `expected_consent_review_version`, carrying the review `version` the landlord last observed. If the review's current `version` no longer matches, the decision is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412), since the decision would rest on a review record the landlord has not observed. Endpoints not named in this subsection take no version field at all.

### 2.8. Validation Order and Request Integrity

A request body with a required field missing, a field outside the endpoint's schema, an unknown enum value, or a type mismatch is rejected outright with `ERR_INVALID_REQUEST` (HTTP 400); body validation runs after authentication and role authorization and ahead of every remaining check. Beyond that, when several checks could reject the same request, the server evaluates them in one fixed order, and a failure at any step masks every later check: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of path-referenced resources (`ERR_NOT_FOUND`), then referential integrity of supplied foreign keys (`ERR_FK_MISMATCH`), then state validity for the invoked transition (`ERR_INVALID_STATE`), then segregation of duties (`ERR_DUTY_SEGREGATION`), then temporal windows (`ERR_TEMPORAL_WINDOW`), then uniqueness and exclusivity (`ERR_DUPLICATE_ACTIVE`), then package completeness (`ERR_PACKAGE_INCOMPLETE`), then fiscal coherence (`ERR_FISCAL_INCOHERENT`), then the consent-decision window (`ERR_CONSENT_WINDOW_LAPSED`), then reminder eligibility (`ERR_REMINDER_PREMATURE`), and finally the two optimistic-concurrency checks (`ERR_STALE_LEASE_VERSION` ahead of `ERR_STALE_REVIEW_VERSION`). Two refinements belong to specific endpoints and are stated where they apply: on the reminder capability, `ERR_DEEMED_APPROVAL_DISABLED` takes precedence over `ERR_REMINDER_PREMATURE`, and measurement revision-integrity failures report `ERR_MEASUREMENT_SUPERSEDED` rather than `ERR_PACKAGE_INCOMPLETE`.

Existence is validated left-to-right along the URL path. When a path contains more than one identifier — a lease before its transfer, a transfer before its review — the first identifier that does not resolve to an existing resource produces the `ERR_NOT_FOUND` (HTTP 404) rejection, before any later identifier is examined.

### 2.9. Party Identity and Segregation of Duties

Four workflows bind the caller's identity to a specific party or recorded originator, and a breach of any of them is rejected with `ERR_DUTY_SEGREGATION` (HTTP 403). The broker attesting a credit review must differ from the broker who originated the transfer — the same hands that marketed the space may not vouch for the counterparty's credit. The broker withdrawing a transfer must be the broker whose identifier is recorded as that transfer's `broker_user_id`. The landlord deciding a consent review must be the lease's landlord of record, with `X-User-ID` equal to the lease's `landlord_party_id`. The tenant responding to a consent condition must be the lease's tenant of record, with `X-User-ID` equal to the lease's `tenant_party_id`. No other write binds the caller to a recorded identity: originating, submitting, measuring, and documenting a transfer, and creating, finalizing, or voiding a settlement, require only the `TenantRepBroker` role, and the deemed-approval reminder requires only the `Tenant` role — none of these consults the recorded `broker_user_id` or the lease's `tenant_party_id`.

Signature ceremonies carry their own identity check. Signing with `signatory` set to `LANDLORD` requires the caller's `X-User-ID` to equal the lease's `landlord_party_id`; signing with `signatory` set to `COUNTERPARTY` requires it to equal the transfer's `counterparty_id`; and neither side may sign twice. Any mismatch is rejected with `ERR_SIGNATORY_MISMATCH` (HTTP 403).

### 2.10. Derived Fields, Cascades, and the Lease Ledger

The lease is the domain's ledger anchor, and two of its fields are maintained by the server rather than written by clients. `cumulative_profit_share_cents` is the running total of the landlord's profit share across all `FINALIZED` settlements of the lease; it is debited at the moment a settlement finalizes, voiding a `DRAFT` settlement has no ledger effect, and a finalized settlement cannot be voided at all. `open_transfer_count` counts the lease's transfers that sit in a non-terminal status and drives the one-open-transfer gate of §3.2; it is incremented at submission and decremented when a transfer reaches denial, rescission, withdrawal from a post-draft state, or effectiveness.

State changes propagate across aggregate boundaries immediately, inside the same request that triggers them: certifying a revised measurement supersedes its predecessor, a second recognition signature advances both the transfer and the instrument, and finalizing a settlement debits the lease. Each such cascade mutates every resource it touches — status flips, timestamps set, counters moved — with the `updated_at` and `version` consequences of §2.4.

## 3. Business Logic & Workflows

### 3.1. Portfolio Onboarding: Parties, Buildings, and Leases

Before any transfer can be negotiated, an `AssetManager` registers the cast. A party is registered with its `legal_name`, a `party_kind` of `LANDLORD`, `TENANT`, `SUBTENANT`, or `ASSIGNEE`, and a `credit_rating_bps` score between 0 and 10000 that the credit review later consults — a score outside that range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The parties listing supports an optional `party_kind` filter, and any single party can be fetched by its `id`.

Buildings come next, registered with a display `name`, a strictly positive `total_rentable_sf` that serves as the denominator for pro-rata shares, and a `loss_factor_bps` between 0 and 5000 describing the building's markup from usable to rentable area. A non-positive `total_rentable_sf` or a `loss_factor_bps` outside that range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). From a building, the leases housed in it are reachable as a list.

A lease is created against a `building_id` and two parties: `tenant_party_id`, which must reference a party of kind `TENANT`, and `landlord_party_id`, which must reference a party of kind `LANDLORD`. A reference that is missing or points at the wrong kind of party — a landlord slot holding a tenant, for instance — is rejected with `ERR_FK_MISMATCH` (HTTP 422), as is a `building_id` that resolves to no registered building. The economic terms supplied at creation are the strictly positive `base_rent_per_rsf_annual_cents` and the strictly positive `leased_rsf` anchoring partial-floor comparisons — a non-positive value in either is rejected with `ERR_FISCAL_INCOHERENT` (HTTP 422) — the `consent_window_business_days` the landlord has to respond (at least 1 and at most 60, a value outside that range rejected as `ERR_INVALID_REQUEST`, HTTP 400), the `deemed_approval_enabled` flag that decides whether landlord silence can ripen into consent, and the two-tier profit split: `profit_share_tier1_pct_bps` up to the `profit_share_tier1_threshold_annual_cents` of annual net profit (a threshold of zero or more) and `profit_share_tier2_pct_bps` above it. Fiscal coherence forbids a tier-two percentage below the tier-one percentage; such a lease is rejected with `ERR_FISCAL_INCOHERENT` (HTTP 422). No further range validation applies at creation — the tier percentages and the tier-one threshold are stored as supplied, with only the ordering rule enforced. A new lease starts with `status` of `ACTIVE` — this administration surface manages transfers on active leases only, and lease expiry or termination is outside the transfer-consent domain — with `open_transfer_count` and `cumulative_profit_share_cents` both zero. Leases can be listed with optional `landlord_party_id` and `tenant_party_id` filters, and from a lease its transfers, its settlements, and the measurements taken under it are all reachable as lists.

### 3.2. Originating a Transfer Request

A `TenantRepBroker` originates a transfer against a lease, supplying the `counterparty_id` of the proposed subtenant or assignee, the `transfer_type`, a strictly positive `proposed_rent_per_rsf_annual_cents`, the proposed `term_start` and `term_end`, the `marketing_period_days` the space has already been advertised (recorded as supplied — no lower bound is enforced at creation, the thirty-day floor of §3.4 biting only at submission), and the OCC field `expected_lease_version` per §2.7. The server records the caller's opaque identifier as the transfer's `broker_user_id`, which later bars the same broker from attesting the counterparty's credit. The counterparty's kind must match the transfer flavor — a `SUBLEASE` demands a `SUBTENANT` counterparty and an `ASSIGNMENT` an `ASSIGNEE` — with mismatches rejected as `ERR_FK_MISMATCH`. The choice of flavor is consequential: a `SUBLEASE` retains the tenant's privity and liability, while an `ASSIGNMENT` novates the lease and, subject to the consent terms, can release the assignor.

Exclusivity is enforced at creation. A lease may carry at most one non-terminal transfer — one whose `status` has not reached `EFFECTIVE`, `WITHDRAWN`, `RESCINDED`, or `CONSENT_DENIED` — and a create that would open a second is rejected with `ERR_DUPLICATE_ACTIVE` (HTTP 409). A non-positive proposed rent is rejected as `ERR_FISCAL_INCOHERENT`. Creation starts the transfer in `DRAFT` and increments the lease's `version` by one as the OCC anchor, but does not touch `open_transfer_count`; that counter moves only at submission. The transfer collection can be listed with `lease_id`, `status`, `transfer_type`, and `counterparty_id` filters, and a single fetch exposes the computed `consent_deadline` and `annual_rent_differential_cents` alongside the stored fields.

### 3.3. Measuring the Demised Premises

Every transfer needs a certified measurement of the space changing hands before it can be submitted. The originating broker creates a measurement record beneath the transfer — the `lease_id` association is derived from the parent transfer rather than supplied by the client — providing a `measurement_standard` of `METHOD_A` or `METHOD_B`, a strictly positive `usable_sf` (a non-positive value is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and, for a re-measurement, an optional `supersedes_id` pointing at the record being revised. A new record starts in `DRAFT`, and while it remains there its derived values are provisional: each read recomputes them against the building's current loss factor, so a draft measurement silently tracks building changes.

Certification freezes the numbers. When the broker certifies a record — permitted only while the parent transfer sits in `DRAFT`, `SUBMITTED`, or `CONSENT_PENDING`, with attempts in any other transfer state rejected as `ERR_INVALID_STATE` — the server computes and freezes three derived values in a pinned order. First `rentable_sf`: under `METHOD_A`, the `usable_sf` multiplied by ten thousand plus the building's `loss_factor_bps`, the product divided by ten thousand, and the quotient rounded half-up to a whole square foot; under `METHOD_B`, the same shape but with the loss factor integer-halved — the basis-point value divided by two with any remainder discarded — and a fixed common-area add-on of 250 basis points (two and a half percent) included alongside the halved factor. Second, `prorata_share_bps`: the frozen `rentable_sf` multiplied by ten thousand and divided by the building's `total_rentable_sf`, rounded half-up to an integer basis-point value. Third, `is_partial_floor`: true exactly when the `rentable_sf` is strictly less than the lease's `leased_rsf`, a flag that later triggers the partial-floor expense gross-up in settlement math. Once certified, the record's values are frozen; a later change to the building's loss factor does not alter them.

Revisions form a self-referential chain. A revision must chain off the current certified tip: the referenced record is resolved globally rather than scoped to the same transfer, a `supersedes_id` that resolves to no record at all is rejected with `ERR_NOT_FOUND` (HTTP 404), creating one whose `supersedes_id` references a record that is still `DRAFT` or already `SUPERSEDED` is rejected with `ERR_MEASUREMENT_SUPERSEDED` (HTTP 409), and attempting to certify a record that is itself `SUPERSEDED` draws the same rejection, while certifying a record that is already `CERTIFIED` fails state validation as `ERR_INVALID_STATE` (HTTP 409). When a revision certifies, the record it references flips from `CERTIFIED` to `SUPERSEDED` and its `superseded_by_id` is set to the new record's `id`; a superseded record is thereafter read-only for settlement math. If the parent transfer has already reached `CONSENT_GRANTED` when its certified measurement is superseded, documentation is blocked until a fresh certified, non-superseded measurement exists again — a gate re-evaluated whenever documentation is attempted. The measurements collection lists with `lease_id`, `transfer_request_id`, `supersedes_id`, `superseded_by_id`, and `status` filters, which also exposes the chain in both directions: the revisions of a record and the records a record has superseded.

### 3.4. Submission and the Credit Gate

Submission is the point of no return for the marketing package. When the originating broker submits a `DRAFT` transfer, the server walks its gates in the fixed order of §2.8. The transfer must be in `DRAFT`, else `ERR_INVALID_STATE` (HTTP 409). The term window must be valid — `term_start` strictly after the logical clock's now and `term_end` strictly after `term_start` — else `ERR_TEMPORAL_WINDOW` (HTTP 422); this surface models no lease-expiry check beyond those two rules. The package must be complete, else `ERR_PACKAGE_INCOMPLETE` (HTTP 422): the space must have been marketed for at least thirty days — 720 hours — so `marketing_period_days` below 30 fails, and a certified, non-superseded measurement must exist for the transfer. The parent lease must be `ACTIVE` — a check evaluated last, after package completeness, failing as `ERR_INVALID_STATE` (HTTP 409).

A successful submission stamps `submitted_at` with the logical clock, computes the `consent_deadline`, mints exactly one consent review with `decision` of `PENDING` and exactly one credit review with `outcome` of `PENDING` for the transfer, and increments both the lease's `open_transfer_count` and its `version` by one. The deadline arithmetic is business-day arithmetic per §2.5: counting begins on the first business day strictly after the submission calendar day — for a submission landing on a Saturday or Sunday, counting begins the following Monday — and advances one business day at a time, skipping weekends, until the lease's `consent_window_business_days` count is exhausted; the deadline lands at exactly 17:00:00.000Z on that final counted day.

Credit attestation belongs to a different pair of hands than origination. A broker attests by submitting `reviewed_credit_rating_bps`, the rating verified for the counterparty — a value outside 0–10000 is rejected with `ERR_INVALID_REQUEST` (HTTP 400); if the attesting broker's `X-User-ID` equals the transfer's recorded `broker_user_id`, the attestation is rejected as `ERR_DUTY_SEGREGATION`. Attestation is gated only on the review remaining `PENDING`, whatever the transfer's status: attesting an already-decided review is rejected with `ERR_INVALID_STATE` (HTTP 409). The pass threshold is fixed at `minimum_pass_bps` of 6,000 basis points — sixty percent of the ten-thousand-point scale: a reviewed rating of at least that threshold flips the review from `PENDING` to `PASS`, and anything below it flips the review to `FAIL`. Either outcome stamps `attested_at`, records the caller as `attesting_broker_user_id`, and auto-advances the transfer from `SUBMITTED` to `CONSENT_PENDING`. A `FAIL` does not itself deny the transfer; it arms the landlord's `INSUFFICIENT_CREDIT` denial ground, nothing more. The credit review of a transfer is retrievable beneath the transfer as a zero-or-one-element array.

### 3.5. The Landlord's Consent Decision

While the transfer sits in `SUBMITTED` or `CONSENT_PENDING` and the review remains `PENDING`, the landlord of record decides. The decision payload carries a `decision` of `GRANTED`, `GRANTED_WITH_CONDITIONS`, or `DENIED`, the OCC field `expected_consent_review_version`, and — per branch — a `denial_reason_code`, a `release_of_assignor` election, or a `conditions` array. The server evaluates the guards in order: the review must still be `PENDING` (`ERR_INVALID_STATE`), the caller's `X-User-ID` must equal the lease's `landlord_party_id` (`ERR_DUTY_SEGREGATION`), the decision must arrive at or before the transfer's `consent_deadline` (`ERR_CONSENT_WINDOW_LAPSED`, HTTP 409 — a decision at exactly the deadline is accepted, while one strictly after it is rejected and the review locks pending the deemed-approval evaluation), and the expected version must match (`ERR_STALE_REVIEW_VERSION`), each failure masking the checks after it. A decided review stamps `decided_at`, records the caller as `reviewer_landlord_id`, and increments the review's `version` by one; the decision drives the parent transfer across entity boundaries.

An express grant is the clean branch. `GRANTED` moves the transfer from `SUBMITTED` or `CONSENT_PENDING` to `CONSENT_GRANTED`, stamps `consent_granted_at`, and computes two derived fields. The `annual_rent_differential_cents` is the per-RSF spread — the proposed rent minus the lease's `base_rent_per_rsf_annual_cents`, both annual cents per rentable square foot — multiplied by the certified, non-superseded measurement's `rentable_sf`, with the whole differential clamped at zero when the spread is zero or negative: a sublease at or below the pass-through rent yields zero differential and zero profit share, and the integer-cent result needs no rounding. The `liability_released` flag is true only when the `transfer_type` is `ASSIGNMENT` and the granted review carried `release_of_assignor` set to true; a `SUBLEASE` never releases tenant liability, and `release_of_assignor` defaults to false and is only meaningful for assignments.

A conditional grant forks the workflow. `GRANTED_WITH_CONDITIONS` requires at least one supplied condition — each an entry of `condition_kind` and free-text `detail`, the kind drawn from `RESTORATION_REQUIRED`, `ADDITIONAL_SECURITY`, `RENT_RESET_TO_MARKET`, or `RECAPTURE_RIGHT`, and a decision arriving with an empty or absent `conditions` array is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and creates one consent condition in `PENDING` per supplied entry, recording their number as `conditions_imposed_count`. The transfer does not reach consent yet: it sits in `CONSENT_PENDING` until the conditional-acceptance join resolves, moving there from `SUBMITTED` when the credit gate has not yet run. The tenant of record responds to each condition with a `response` of `ACCEPTED` or `REJECTED` — a respondent whose `X-User-ID` differs from the lease's `tenant_party_id` is rejected as `ERR_DUTY_SEGREGATION`, and a response against a condition whose parent review is no longer `GRANTED_WITH_CONDITIONS` fails state validation, as does a response against a condition that is itself no longer `PENDING` — stamping `responded_at` on the condition, which carries the `consent_review_id` of its parent review. When every condition of the review has reached `ACCEPTED`, the join fires: the transfer moves `CONSENT_PENDING → CONSENT_GRANTED` with the same side effects as an express grant — `consent_granted_at`, the differential computation against the certified measurement, and the liability flag. Any single `REJECTED` condition instead arms rescission: while the transfer is still `CONSENT_PENDING`, the landlord of record may rescind — a caller whose `X-User-ID` differs from the lease's `landlord_party_id` is rejected as `ERR_DUTY_SEGREGATION`, and an attempt against a review no longer `GRANTED_WITH_CONDITIONS` or without at least one `REJECTED` condition fails state validation as `ERR_INVALID_STATE` — moving the review from `GRANTED_WITH_CONDITIONS` to `RESCINDED`, stamping `rescinded_at`, driving the transfer to `RESCINDED`, and decrementing the lease's `open_transfer_count` while incrementing its `version`.

Denial is the third branch and the most constrained. A `DENIED` decision without a `denial_reason_code`, or one citing `INSUFFICIENT_CREDIT` while the credit review's `outcome` is not `FAIL`, is rejected with `ERR_DENIAL_REASON_INVALID` (HTTP 422): the leases administered here permit denial only on enumerated commercially-reasonable grounds. Only `INSUFFICIENT_CREDIT` carries such an evidentiary gate; the remaining enumerated grounds are accepted as cited — `USE_CONFLICT` and `EXISTING_TENANT_SOLICITATION` unconditionally, and `INSUFFICIENT_MARKETING` likewise, though the sub-thirty-day marketing period it asserts is unreachable behind the submission gate. A valid denial moves the transfer from `SUBMITTED` or `CONSENT_PENDING` to the terminal `CONSENT_DENIED` and decrements the lease's `open_transfer_count` while incrementing its `version`. Consent reviews list with `transfer_request_id`, `reviewer_landlord_id`, and `decision` filters; a transfer's single review is also reachable beneath the transfer as a zero-or-one-element array, as are the conditions beneath their review.

### 3.6. Silence as Consent: Reminders and Deemed Approval

Some leases let silence ripen into consent; others do not. Where `deemed_approval_enabled` is false, landlord silence is never consent, and a reminder notice sent on such a lease is rejected with `ERR_DEEMED_APPROVAL_DISABLED` (HTTP 409) — a rejection that takes precedence over `ERR_REMINDER_PREMATURE` when both could apply.

A caller in the `Tenant` role starts the deemed-approval endgame by sending a reminder notice; the reminder is not identity-bound — the server does not compare the caller's `X-User-ID` to the lease's `tenant_party_id` here. Reminder eligibility requires the transfer in `SUBMITTED` or `CONSENT_PENDING`, the consent review still `PENDING`, no reminder previously recorded, and the logical clock strictly after the `consent_deadline`; a notice sent while the clock is still at or before the deadline, after the review has been decided, or twice over is rejected with `ERR_REMINDER_PREMATURE` (HTTP 409). A valid notice stamps `reminder_sent_at` with the logical clock.

Deemed approval then fires from the clock itself. When the clock reaches or passes the instant two business days after the consent deadline — the same business-day counting and the same 17:00:00.000Z landing rule as the deadline itself — and the lease has deemed approval enabled, the review is still `PENDING`, and `reminder_sent_at` is set to an instant at or after the `consent_deadline`, the transfer auto-transitions from `SUBMITTED` or `CONSENT_PENDING` to `DEEMED_APPROVED`. The transition stamps `consent_granted_at`, flips the review's `decision` to `GRANTED` with `decided_at` set, and — because no landlord ever spoke — the deemed grant never carries conditions and never releases the assignor: `release_of_assignor` is forced to false. An express decision at or before the deadline pre-empts this timer entirely; a landlord who waits past it without deciding has, on an enabled lease, consented.

### 3.7. Documentation, Recognition, and Effectiveness

Once consent has landed — whether as `CONSENT_GRANTED` or `DEEMED_APPROVED` — a `TenantRepBroker` documents the transfer; documenting from any other transfer state is rejected with `ERR_INVALID_STATE` (HTTP 409). Documentation requires a certified, non-superseded measurement to still exist for the transfer; a measurement revised after consent blocks documentation as `ERR_PACKAGE_INCOMPLETE` until a fresh certification exists. The payload carries `executed_rent_per_rsf_annual_cents` and an optional `restoration_allocations` array. The executed rent must equal the transfer's `proposed_rent_per_rsf_annual_cents`, unless consent was granted with a `RENT_RESET_TO_MARKET` condition that the tenant accepted, in which case the executed rent may differ and the transfer's differential is thereafter recomputed on the documented basis — the executed rent standing in for the proposed rent while the square footage stays pinned to the same certified measurement. A non-positive `executed_rent_per_rsf_annual_cents`, or one unequal to the proposed rent without an accepted `RENT_RESET_TO_MARKET` condition, is rejected with `ERR_FISCAL_INCOHERENT` (HTTP 422).

Documentation fans out into three creations. For a `SUBLEASE`, an instrument is minted in `EXECUTED` status, stamped with `executed_at`, recording the executed rent as `executed_rent_per_rsf_annual_cents`, and pinned to the certified measurement through its `demised_area_id` — version-pinning on approval, so the closing paper always names the exact measurement it relies on; an `ASSIGNMENT` records no instrument — the executed rent then persists only through the recomputed differential — and the receipt's instrument reference is null. A recognition agreement is always drafted, entering `DRAFTED` with its `sublease_agreement_id` set for a sublease and null for an assignment. And for each accepted `RESTORATION_REQUIRED` condition, a restoration obligation is created in `OPEN`, carrying the negotiated `responsible_party` — `TENANT`, `SUBTENANT_OR_ASSIGNEE`, or `SHARED` — and `escrow_amount_cents` taken from the matching entry of `restoration_allocations` — entries matched to the accepted `RESTORATION_REQUIRED` conditions positionally in the conditions' creation order, too few entries rejected as `ERR_INVALID_REQUEST` (HTTP 400) and surplus entries ignored; fiscal coherence demands a strictly positive escrow whenever the responsible party is anything other than `TENANT`, else `ERR_FISCAL_INCOHERENT`, and an obligation recorded with a positive escrow auto-advances from `OPEN` to `ESCROW_POSTED`. The transfer itself moves to `DOCUMENTED`, and the broker receives a 201 documentation receipt naming the `transfer_request_id`, the `sublease_agreement_id` (null for assignments), and the `recognition_agreement_id` (always set).

Recognition is the two-signature ceremony that makes the transfer effective. Either side may sign first: a `signatory` of `LANDLORD` from the lease's landlord of record, or `COUNTERPARTY` from the transfer's counterparty, each identity-checked per §2.9. The first signature moves the agreement from `DRAFTED` to `PARTIALLY_SIGNED` and stamps `landlord_signed_at` or `counterparty_signed_at` according to the signing side. The second signature, from the opposite side, moves it from `PARTIALLY_SIGNED` to `FULLY_EXECUTED` and stamps the remaining signature field; a side that has already signed signing again, or a caller whose identity does not match the declared `signatory`, is rejected with `ERR_SIGNATORY_MISMATCH`. Full execution cascades two hops: the transfer moves `DOCUMENTED → EFFECTIVE` with `effective_at` stamped and the lease's `open_transfer_count` decremented and `version` incremented, and — for a sublease only — the instrument moves `EXECUTED → RECOGNIZED`. Effectiveness is what unlocks settlement finalization: draft settlements may be created from `CONSENT_GRANTED` or `DEEMED_APPROVED` onward, but finalizing one requires the transfer to be `EFFECTIVE`. The recognition agreement of a transfer is reachable beneath the transfer as a zero-or-one-element array and lists with `transfer_request_id`, `sublease_agreement_id`, and `status` filters; instruments likewise list with `transfer_request_id`, `status`, and `demised_area_id` filters.

### 3.8. Settlements and the Profit-Sharing Waterfall

Once consent has been granted, the broker may open a settlement against the transfer to reconcile the landlord's profit share for an accrual period. Creation supplies the `lease_id`, the `transfer_request_id`, the half-open period — `period_start` inclusive, `period_end` exclusive, with an end not strictly after its start rejected as `ERR_TEMPORAL_WINDOW` — and the `subrent_collected_cents` actually collected in the period, never the billed figure, with a negative collection rejected as `ERR_FISCAL_INCOHERENT`. Supplied references that do not resolve to an existing lease and an existing transfer fail referential integrity as `ERR_FK_MISMATCH`, as does a `transfer_request_id` naming a transfer that belongs to a different lease. The referenced transfer must sit in `CONSENT_GRANTED`, `DEEMED_APPROVED`, `DOCUMENTED`, or `EFFECTIVE`, and if an instrument exists for the transfer it must not be `TERMINATED`; otherwise creation fails as `ERR_INVALID_STATE`. If no certified measurement can be resolved to feed the waterfall, creation fails as `ERR_PACKAGE_INCOMPLETE` (HTTP 422) — a check evaluated after the fiscal-coherence gate, refining the global order of §2.8 for this endpoint. The transfer's settlements are also reachable beneath the transfer and beneath the lease, and the settlements collection lists with `lease_id`, `transfer_request_id`, and `status` filters.

Creation computes every derived field immediately, in a pinned order that must not be rearranged. The day count is the number of whole days from `period_start` up to but not including `period_end`. The base pass-through is the lease's `base_rent_per_rsf_annual_cents` multiplied by the certified measurement's `rentable_sf` and by the day count, divided by the 365-day year, rounded half-up to whole cents — the first rounding step. When the demised area's `is_partial_floor` is true, the pass-through is then grossed up by 1,500 basis points (fifteen percent) — the base multiplied by eleven thousand five hundred and divided by ten thousand, rounded half-up as a second, nested rounding step — yielding `passthrough_rent_cents`; a full-floor demise skips the gross-up and keeps the base figure. The `net_profit_cents` is the collected subrent minus the pass-through, floored at zero. The annualized profit is the net profit multiplied by 365 and divided by the day count, rounded half-up. The tier-1 base is the lesser of that annualized profit and the lease's `profit_share_tier1_threshold_annual_cents`; the tier-2 base is whatever annualized profit exceeds the threshold, or zero. Each tier's landlord share is its base multiplied by the tier's percentage in basis points and divided by ten thousand, rounded half-up per tier — the per-tier rounding is pinned ahead of summation, never the reverse — and the two rounded tier amounts sum to the annualized landlord share. Finally `landlord_share_cents` de-annualizes: the annualized landlord share multiplied by the day count and divided by 365, rounded half-up as the third rounding step. The `tenant_share_cents` is the net profit minus the landlord's share; it is deliberately not floored and may go negative when the landlord's share exceeds the period's net. The measurement feeding all of this is, for a documented sublease, the certified record pinned by the instrument, and otherwise — a sublease not yet documented, like every assignment — the transfer's certified, non-superseded record.

While a settlement sits in `DRAFT`, its computed fields are provisional — recomputed on every read — and the lease ledger is untouched. Finalization — permitted only while the settlement itself is `DRAFT`, attempts against a `FINALIZED` or `VOID` settlement rejected as `ERR_INVALID_STATE` (HTTP 409), and restricted to a transfer that has reached `EFFECTIVE` with no `TERMINATED` instrument — freezes the computed fields, stamps `finalized_at`, and debits the ledger: the lease's `cumulative_profit_share_cents` increases by the settlement's `landlord_share_cents`, and the lease's `version` increments by one. Finalized periods for the same transfer must not overlap — the check treats each period as half-open, so one period's `period_end` equaling another's `period_start` is permitted adjacency rather than overlap — and an overlapping finalization is rejected with `ERR_DUPLICATE_ACTIVE`. A draft settlement may instead be voided, moving it to `VOID` with no ledger effect; voiding a settlement in any other status — `FINALIZED` or `VOID` alike — is rejected with `ERR_INVALID_STATE` (HTTP 409), so a finalized settlement can never be voided.

### 3.9. Restoration Obligations and Transfer End-of-Life

Restoration duties are born at documentation and discharged by the landlord. Completion of an obligation still in `OPEN` requires either that the `responsible_party` is `TENANT` or that no escrow stands posted — breaching that gate is rejected with `ERR_INVALID_STATE` (HTTP 409) — while completion from `ESCROW_POSTED` has no such gate, and either path stamps `completed_at` and moves the obligation to `COMPLETED`, with any escrow released out of band. The landlord may instead waive an obligation from `OPEN` or `ESCROW_POSTED`, moving it to `WAIVED`. Both completion and waiver bind the caller to the lease's landlord of record — a caller whose `X-User-ID` differs from the lease's `landlord_party_id` is rejected with `ERR_DUTY_SEGREGATION` (HTTP 403) — and acting on an obligation in any status other than `OPEN` or `ESCROW_POSTED` fails state validation as `ERR_INVALID_STATE` (HTTP 409).

Transfers exit the workflow through several doors. Withdrawal belongs to the originating broker alone — a withdrawer whose `X-User-ID` differs from the transfer's `broker_user_id` is rejected as `ERR_DUTY_SEGREGATION` — and its consequences depend on how far the transfer had travelled. From `DRAFT`, withdrawal moves the transfer to `WITHDRAWN` with no change to `open_transfer_count`, which was never incremented. From `SUBMITTED` or `CONSENT_PENDING`, withdrawal additionally decrements that counter, increments the lease's `version`, and voids any drafted or partially-signed recognition agreement attached to the transfer. From `CONSENT_GRANTED` or `DEEMED_APPROVED`, withdrawal decrements the counter and increments the version. From `DOCUMENTED`, withdrawal is possible only while the recognition agreement has not reached `FULLY_EXECUTED` — an executed recognition locks the transfer, and withdrawal after effectiveness is impossible — and it triggers the full compensation cascade: the drafted or partially-signed recognition agreement flips to `VOIDED`, an `EXECUTED` sublease instrument flips to `TERMINATED`, and every restoration obligation of the transfer in `OPEN` or `ESCROW_POSTED` flips to `WAIVED`. The same `VOIDED` cascade applies whenever a parent transfer enters `WITHDRAWN` or `RESCINDED`. Withdrawal attempted from a terminal status — `CONSENT_DENIED`, `RESCINDED`, `WITHDRAWN`, or `EFFECTIVE` — is rejected with `ERR_INVALID_STATE` (HTTP 409).

Termination of the instrument is the tenant's own exit. The tenant of record — `X-User-ID` equal to the lease's `tenant_party_id`, any other caller rejected as `ERR_DUTY_SEGREGATION` (HTTP 403) — may terminate an instrument in `EXECUTED` or in `RECOGNIZED`, moving it to `TERMINATED`, an instrument in any other status failing state validation as `ERR_INVALID_STATE` (HTTP 409); from that point no settlement may be created or finalized against the parent transfer, an existence gate the settlement workflows enforce as `ERR_INVALID_STATE`. Together with denial, rescission, withdrawal, and effectiveness, these doors define the transfer's terminal landscape of `CONSENT_DENIED`, `RESCINDED`, `WITHDRAWN`, and `EFFECTIVE`, each releasing the lease's one-open-transfer gate for the next deal.

## 4. Endpoint Definitions

Operations that create a new resource — a party, building, lease, transfer request, measurement, settlement, or the documentation receipt — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`, as do all retrievals. The table below is a navigational summary only; request payloads, derived fields, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sublease-admin/parties` | Register a party (landlord, tenant, subtenant, assignee) | AssetManager |
| GET | `/sublease-admin/parties` | List parties with optional kind filter | Any authenticated role |
| GET | `/sublease-admin/parties/{id}` | Fetch one party | Any authenticated role |
| POST | `/sublease-admin/buildings` | Register a building with total RSF and loss factor | AssetManager |
| GET | `/sublease-admin/buildings/{id}` | Fetch one building | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/buildings/{id}/leases` | List the leases housed in a building | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/leases` | Create a lease (starts ACTIVE with zeroed counters) | AssetManager |
| GET | `/sublease-admin/leases/{id}` | Fetch one lease including computed ledger fields | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/leases` | List leases with optional landlord/tenant filters | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/leases/{id}/transfer-requests` | List the transfers of a lease | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/leases/{id}/settlements` | List the settlements of a lease | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/leases/{id}/demised-areas` | List measurements of all transfers under a lease | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/leases/{lease_id}/transfer-requests` | Create a transfer request (DRAFT) against a lease; OCC-guarded | TenantRepBroker |
| GET | `/sublease-admin/transfer-requests/{id}` | Fetch one transfer including computed deadline and differential | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/transfer-requests` | List transfers filtered by lease, status, type, or counterparty | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/transfer-requests/{id}/submit` | Submit a transfer: completeness gates, review minting, consent clock start | TenantRepBroker |
| POST | `/sublease-admin/transfer-requests/{id}/withdraw` | Withdraw a transfer; only the originating broker may withdraw | TenantRepBroker |
| POST | `/sublease-admin/transfer-requests/{id}/remind` | Send the deemed-approval reminder notice after the deadline | Tenant |
| POST | `/sublease-admin/transfer-requests/{id}/document` | Document a granted transfer: instrument, recognition draft, restoration duties | TenantRepBroker |
| GET | `/sublease-admin/transfer-requests/{id}/consent-review` | Fetch the consent review of a transfer (array of 0–1) | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/transfer-requests/{id}/credit-review` | Fetch the credit review of a transfer (array of 0–1) | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/transfer-requests/{id}/demised-areas` | List the measurements of a transfer | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/transfer-requests/{id}/recognition-agreement` | Fetch the recognition agreement of a transfer (array of 0–1) | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/transfer-requests/{id}/restoration-obligations` | List the restoration obligations of a transfer | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/transfer-requests/{id}/settlements` | List the settlements of a transfer | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/transfer-requests/{id}/demised-areas` | Create a measurement record (DRAFT); optional revision link | TenantRepBroker |
| GET | `/sublease-admin/demised-areas/{id}` | Fetch one measurement (provisional values recomputed while DRAFT) | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/demised-areas` | List measurements with lease, transfer, revision-chain, and status filters | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/demised-areas/{id}/certify` | Certify a measurement: freeze values, supersede the referenced prior record | TenantRepBroker |
| GET | `/sublease-admin/consent-reviews/{id}` | Fetch one consent review | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/consent-reviews` | List consent reviews filtered by transfer, reviewer, or decision | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/consent-reviews/{id}/decide` | Landlord decision: grant, grant with conditions, or deny; OCC-guarded | Landlord |
| POST | `/sublease-admin/consent-reviews/{id}/rescind` | Rescind a conditional grant after a tenant rejection | Landlord |
| GET | `/sublease-admin/consent-reviews/{id}/conditions` | List the conditions of a review | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/consent-conditions/{id}/respond` | Tenant accepts or rejects one condition; all-accepted join grants consent | Tenant |
| GET | `/sublease-admin/consent-conditions/{id}` | Fetch one condition | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/credit-reviews/{id}` | Fetch one credit review | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/credit-reviews/{id}/attest` | Attest counterparty credit; PASS at or above 6,000 bps; segregation enforced | TenantRepBroker |
| GET | `/sublease-admin/sublease-agreements/{id}` | Fetch one instrument | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/sublease-agreements` | List instruments filtered by transfer, status, or pinned measurement | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/sublease-agreements/{id}/terminate` | Tenant terminates an instrument; blocks further settlements | Tenant |
| GET | `/sublease-admin/recognition-agreements/{id}` | Fetch one recognition agreement | Any authenticated role |
| GET | `/sublease-admin/recognition-agreements` | List recognition agreements filtered by transfer, instrument, or status | Any authenticated role |
| POST | `/sublease-admin/recognition-agreements/{id}/sign` | Sign as LANDLORD or COUNTERPARTY; second signature executes and cascades | Landlord, Subtenant, Assignee |
| POST | `/sublease-admin/settlements` | Create a settlement over a half-open period; derived fields computed at creation | TenantRepBroker |
| GET | `/sublease-admin/settlements/{id}` | Fetch one settlement (provisional recompute while DRAFT) | AssetManager, Landlord, Tenant, TenantRepBroker |
| GET | `/sublease-admin/settlements` | List settlements filtered by lease, transfer, or status | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/settlements/{id}/finalize` | Finalize: freeze fields, debit the lease ledger, enforce non-overlap | TenantRepBroker |
| POST | `/sublease-admin/settlements/{id}/void` | Void a DRAFT settlement (no ledger effect) | TenantRepBroker |
| GET | `/sublease-admin/restoration-obligations/{id}` | Fetch one restoration obligation | AssetManager, Landlord, Tenant, TenantRepBroker |
| POST | `/sublease-admin/restoration-obligations/{id}/complete` | Landlord certifies restoration complete | Landlord |
| POST | `/sublease-admin/restoration-obligations/{id}/waive` | Landlord waives the restoration obligation | Landlord |
| POST | `/sublease-admin/_clock/set_current_utc` | Set the logical clock; advancing evaluates deemed-approval transitions | AssetManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUTY_SEGREGATION` | 403 Forbidden |
| `ERR_TEMPORAL_WINDOW` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE` | 409 Conflict |
| `ERR_PACKAGE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_FISCAL_INCOHERENT` | 422 Unprocessable Entity |
| `ERR_CONSENT_WINDOW_LAPSED` | 409 Conflict |
| `ERR_DEEMED_APPROVAL_DISABLED` | 409 Conflict |
| `ERR_REMINDER_PREMATURE` | 409 Conflict |
| `ERR_STALE_LEASE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_REVIEW_VERSION` | 412 Precondition Failed |
| `ERR_DENIAL_REASON_INVALID` | 422 Unprocessable Entity |
| `ERR_MEASUREMENT_SUPERSEDED` | 409 Conflict |
| `ERR_SIGNATORY_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
