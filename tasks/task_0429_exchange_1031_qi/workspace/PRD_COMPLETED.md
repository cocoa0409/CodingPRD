# Exchange 1031 QI API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the **1031 Exchange Qualified Intermediary (QI) API**, a back-office platform that lets a qualified intermediary administer like-kind property exchanges under Section 1031 of the U.S. tax code. When a taxpayer sells an investment property and intends to defer the gain by acquiring a replacement, the proceeds may never touch the taxpayer's hands; instead they are held by a neutral intermediary in a qualified trust until they fund the replacement acquisition. The API models that custodial relationship end to end: registering the taxpayer principal, opening the exchange, holding the relinquished-sale proceeds in trust, tracking the two statutory deadlines that govern the transaction, recording which candidate properties the taxpayer identifies, computing the boot and recognized gain when replacements are acquired, and disbursing trust funds under a strict four-eyes financial control.

The platform's chief value is *correctness under deadline pressure*. The Internal Revenue Code grants the taxpayer exactly 45 calendar days from the relinquished closing to formally identify candidate replacements, and exactly 180 calendar days to close on them; missing either deadline disqualifies the exchange and triggers immediate taxation. The system therefore treats time as a first-class driver: a derived **compliance posture** is recomputed against a logical clock on every relevant read and mutation, and that posture gates whether replacements may be acquired or trust funds released. Layered on top of the deadline machinery are the identification breadth rules (the three-property and 200% tests), the boot-and-gain arithmetic that distinguishes ordinary, reverse, and improvement exchanges, a priority-ordered disbursement waterfall, and the segregation-of-duties rule that prevents the coordinator who set up an exchange from also approving its money movements.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting operator, and `X-User-Role` declares the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles, spelled precisely: `QICoordinator`, `SettlementOfficer`, and `Exchanger`.

The `QICoordinator` is the qualified-intermediary operator who sets up exchanges, attaches properties, opens trusts, manages identifications, records replacement acquisitions, and requests disbursements. When `X-User-Role` is `QICoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the exchange at creation time as `coordinator_user_id`, but it does not compare it to any entity's `id`; its only downstream use is the segregation-of-duties check at disbursement approval.

The `SettlementOfficer` is the independent financial controller who approves and voids disbursements of trust funds. When `X-User-Role` is `SettlementOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server records it on a disbursement at approval time as `settlement_officer_user_id` but does not compare it to any entity's `id`. Because of the four-eyes rule described later, this opaque identifier must differ from the coordinator who set up the same exchange.

The `Exchanger` is the taxpayer principal and has read-only visibility into their own exchanges, trust balances, identifications, and disbursements. When `X-User-Role` is `Exchanger`, `X-User-ID` is the `id` of the acting `Exchanger` entity; ownership checks on any resource that references an `Exchanger` compare the resource's `exchanger_id` (directly on an exchange, or transitively through the exchange on its child and cross-aggregate resources) to `X-User-ID`.

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

The top-level collection list endpoints — `GET /exchanges`, `GET /replacement-properties`, and `GET /disbursements` — are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100 (a `limit` outside that range, or a non-integer `limit`/`offset`, is rejected with `ERR_INVALID_REQUEST`). The `offset` parameter is the number of leading items to skip and defaults to 0, and a negative `offset` is rejected with `ERR_INVALID_REQUEST`. The nested per-parent list endpoints (an exchange's relinquished-properties, trust, identifications, and replacement-properties, and an identification's candidates) are not paginated: they ignore `limit`/`offset`, return every matching row, and their envelope `meta` carries no pagination fields.

Unless stated otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Because the logical clock supplies `created_at` and may not advance between successive creations, resources can share an identical `created_at`; such ties are broken by the server's monotonic creation sequence, so resources created earlier still sort earlier.

Paginated list responses surface four fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Most resources in this system — exchangers, exchanges, relinquished properties, qualified trusts, identifications, replacement properties, and disbursements — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the most recent modification. It is refreshed on every mutation of the resource, including mutations to derived fields such as a trust's `available_balance` or an exchange's `compliance_posture`.
- `version` (integer): a counter starting at 1 that increments by one on every modification of the resource. It underpins optimistic concurrency control where applicable.

One entity is deliberately leaner: the **identified candidate property** (`IdentifiedProperty`) carries only `id` and `created_at`. It has neither an `updated_at` nor a `version` field — once added to a draft identification it is treated as an immutable line item whose only mutations are status reclassifications driven by its parent. All other listed resources carry the full four-field set.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address resources nested under an exchange or an identification. When a path carries more than one resource identifier, the server validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` at the *first* identifier that does not resolve to a stored entity. A request for an identification's candidates under a non-existent exchange, for example, fails on the exchange before the identification or the candidate list is ever consulted. This left-to-right existence rule is the third validation in the global ordering described in §2.10, applying uniformly to reads, creations, and state-changing operations.

### 2.6. Monetary Precision and Rounding

Every monetary quantity in the system — sale prices, proceeds, trust balances, boot legs, gains, and disbursement amounts — is carried and stored to exactly **2 decimal places**, and every rounding step uses the **round half up** convention. Where a calculation aggregates or compares figures, the comparison operands are themselves 2-decimal values, so the `min`/`max` selections and subtractions described in §3 operate on already-rounded operands rather than on raw floating-point intermediates. Counts (such as the number of candidate properties) are exact integers and are never rounded.

### 2.7. The Logical Clock

Because the entire compliance model turns on two calendar deadlines, the server runs on a **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and until an explicit set call is made it stays at this default and never falls back to real wall-clock time. An operator may move the clock to any absolute UTC instant by supplying a `to_iso8601` value to the clock-setting capability; subsequent posture computations, deadline comparisons, and timestamp stampings all read from this logical clock. This is what makes 45-day and 180-day behavior reproducible in testing.

### 2.8. Compliance Posture as a Derived Gate

Every exchange exposes a `compliance_posture` that is *computed*, never set directly by a client. It is recomputed on every relevant mutation and lazily on every read of the exchange against the current logical clock. The lazy recompute re-stamps the exchange (refreshing `updated_at` and incrementing `version`) only when the recomputed posture differs from the stored value; a read whose recompute leaves the posture unchanged does not bump `version`, whereas a read that, say, slides the posture from `OPEN` to `AT_RISK` does. Its five values are `OPEN`, `IDENTIFIED`, `AT_RISK`, `COMPLETED`, and `FAILED`:

- `OPEN` once the relinquished leg has closed but before any identification is finalized.
- `IDENTIFIED` once a finalized identification exists for the exchange.
- `AT_RISK` once the 45-day identification deadline (`id_deadline_at`) passes with no finalized identification, or once the 180-day exchange deadline (`exchange_deadline_at`) passes before the exchange is completed.
- `COMPLETED` once all identified replacement value has been acquired and boot has been finalized.
- `FAILED` once a deadline lapses irrecoverably.

Posture is the master gate: it determines whether replacement acquisitions and disbursement operations may proceed, as detailed throughout §3.

Alongside posture, every exchange also carries a coarser lifecycle `status` — one of `DRAFT`, `ACTIVE`, `COMPLETED`, `FAILED`, or `TERMINATED` — which mirrors the latest accepted lifecycle transition and defaults to `DRAFT` at creation.

### 2.9. Hierarchical Consistency and Cascades

Exchanges sit at the top of an aggregate that contains relinquished properties, the qualified trust, and identifications; replacement properties and disbursements reference an exchange across aggregate boundaries. Several operations mutate more than one resource at once, and each affected resource is independently re-stamped — its `updated_at` is refreshed and, where it carries one, its `version` increments. The principal cascades are:

- Closing the relinquished leg deposits the computed net proceeds into the qualified trust, advancing both the exchange and the trust.
- Finalizing an identification flips the parent exchange's posture to `IDENTIFIED`.
- Revoking a draft identification withdraws each of its still-listed candidate line items.
- Recording a replacement acquisition reclassifies the linked candidate to `ACQUIRED` and recomputes the exchange's gain figures.
- Completing or failing an exchange locks the qualified trust.
- Approving a disbursement debits the trust; voiding a previously settled disbursement credits it back.

Each cascade bumps the `version` of every resource it touches that carries a version field. The exact preconditions and downstream effects are specified in the workflow narratives of §3.

### 2.10. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first (a missing or malformed header yields `ERR_UNAUTHENTICATED`), then authorization of the acting role (`ERR_UNAUTHORIZED`), then left-to-right existence of every referenced resource (`ERR_NOT_FOUND`), then request-body well-formedness — required fields present and correctly typed, enums within their declared sets, and numeric bounds satisfied (`ERR_INVALID_REQUEST`). The existence check at priority 3 covers resource identifiers carried in the URL *path*; identifiers supplied in the request *body* (such as the `exchanger_id` on exchange creation, the `identified_property_id` on a replacement, or the `exchange_id`/`replacement_property_id` on a disbursement) are resolved for existence only after the body has passed well-formedness, so a malformed body on such a request yields `ERR_INVALID_REQUEST` even when a body-referenced identifier does not resolve. Only after those four global gates pass does the server evaluate state-machine legality (`ERR_INVALID_STATE` when the target entity is not in a state from which the requested transition is defined) and the domain-specific business rules. Each business rule's own relative ordering is described where that rule lives in §3; for instance, on disbursement approval the segregation-of-duties check, the trust-lock check, and the sufficient-funds check each guard the same operation, and their individual rejection codes are called out in the disbursement narrative.

### 2.11. Optimistic Concurrency Control on Disbursement Creation

Creating a disbursement is the one write in this system guarded by optimistic concurrency control, because a disbursement reserves against the very `available_balance` that another writer may have just drawn down through a settled disbursement. A create request must carry `expected_qualified_trust_version` holding the client's last observed `version` of the exchange's `QualifiedTrust`. If that value does not equal the trust's current `version` — meaning another writer has advanced the trust since the client last read it — the create is rejected with `ERR_STALE_TRUST_VERSION` (HTTP 412), preventing the client from reserving against funds it has not observed. This field is mandatory on the create; it is not an optional override, and no other endpoint in the system takes a version field.

## 3. Business Logic & Workflows

### 3.1. Registering the Taxpayer and Opening an Exchange

Everything begins with the taxpayer principal. A `QICoordinator` registers an **exchanger** by supplying a `legal_name`, a `taxpayer_id`, and an `email`. All three fields are required strings; `legal_name` and `taxpayer_id` must each be non-empty, while `email` is accepted even when empty (it is validated only as a string, not for format or non-emptiness). The `taxpayer_id` is the masked taxpayer identifier and serves as a uniqueness key: an attempt to register a second exchanger with a `taxpayer_id` already in use is rejected with `ERR_DUPLICATE_TAXPAYER_ID`. Once registered, an exchanger is readable by a coordinator, a settlement officer, or by that exchanger themselves.

With a principal on file, the coordinator opens an **exchange** by naming the taxpayer through `exchanger_id` and choosing an `exchange_type` of `FORWARD`, `REVERSE`, or `IMPROVEMENT`. The new exchange begins life in `DRAFT` status, and the opaque `X-User-ID` of the creating coordinator is captured as `coordinator_user_id` — the anchor for the later four-eyes control. At this point `compliance_posture` is not yet meaningful and is serialized as `null`; it becomes `OPEN` only once the relinquished leg closes and the exchange turns `ACTIVE`. A newly created exchange likewise carries `null` for `relinquished_closing_at`, `id_deadline_at`, `exchange_deadline_at`, `realized_gain`, `recognized_gain`, and `deferred_gain` until the relevant transition populates each. Reading an exchange returns its computed posture, both deadline fields, and the gain figures, and the act of reading lazily recomputes posture against the clock before responding; while the exchange remains in `DRAFT` or `TERMINATED` the recompute is a no-op that leaves the posture at its stored value, and the `COMPLETED` and `FAILED` postures are sticky once set by their explicit transitions. Exchanges may also be listed, optionally narrowed to a single principal by an `exchanger_id` filter.

### 3.2. Assembling the Relinquished Leg

Before an exchange can be closed, two children must be attached to it while it is still in `DRAFT`. First, the coordinator attaches exactly one **relinquished property** by posting an `address`, a `fair_market_value`, `selling_expenses`, a `mortgage_payoff`, and an `adjusted_basis`. The `address` is a required string but is accepted even when empty. The sale price `fair_market_value` must be strictly greater than zero; `selling_expenses`, `mortgage_payoff`, and `adjusted_basis` must each be zero or greater. The property's `net_proceeds` is a derived figure that remains zero until the relinquished leg closes. Each relinquished property records the parent exchange through `exchange_id`.

Second, the coordinator opens the **qualified trust** for the exchange, a one-to-one custodial account also tied to its exchange by `exchange_id`. A freshly opened trust starts with `deposited_amount` of zero, `available_balance` of zero, and `is_locked` set to false. Because the trust is strictly one-to-one with the exchange, an attempt to open a second trust on an exchange that already has one is rejected with `ERR_TRUST_ALREADY_EXISTS`. Both the relinquished property and the trust are listable per exchange as arrays of zero or one element; the trust list surfaces the computed `available_balance`.

### 3.3. Closing the Relinquished Leg — Day Zero

Closing the relinquished leg is the pivotal event that starts the statutory clock. It is permitted only when the exchange is still in `DRAFT`, exactly one relinquished property exists for the exchange, and a qualified trust exists for the exchange; if the exchange is not in `DRAFT` the request is rejected with `ERR_INVALID_STATE`. The close advances the exchange from `DRAFT` to `ACTIVE` and performs a tightly ordered set of side effects.

It stamps `relinquished_closing_at` to the current logical clock — this is the Day-0 anchor. From that anchor it derives `id_deadline_at` as the closing instant plus 45 calendar days at the same time of day, and `exchange_deadline_at` as the closing instant plus 180 calendar days at the same time of day. It computes the relinquished property's `net_proceeds` as the `fair_market_value` less the `selling_expenses` less the `mortgage_payoff`, rounded half up to two decimal places; because the inputs are exact cent figures the result is computed in a single step with no intermediate rounding. It computes the exchange's `realized_gain` by first taking the **amount realized** — the `fair_market_value` less the `selling_expenses` — and then subtracting the `adjusted_basis`; for benchmark inputs this figure may be zero but is never negative. The computed `net_proceeds` is then deposited into the qualified trust, credited to both `deposited_amount` and `available_balance` (the cascade from relinquished close to trust deposit). Finally the exchange's posture is recomputed to `OPEN`, its `status` is set to `ACTIVE`, and its `version` increments by one. The trust, having been credited, is independently re-stamped as well.

After Day 0, the passage of time is consequential. If the logical clock advances past `id_deadline_at` while no identification has reached `FINALIZED`, a posture recomputation moves the exchange to `AT_RISK`; this recomputation happens lazily whenever the exchange is read or otherwise mutated, so the exchange remains in `ACTIVE` status but its posture reflects the jeopardy.

### 3.4. Identifying Candidate Replacements

While the exchange is `ACTIVE`, the coordinator creates an **identification** document, declaring the `method` the taxpayer relies on: either `THREE_PROPERTY` or `TWO_HUNDRED_PCT`. A new identification starts in `DRAFT` status with an `aggregate_identified_fmv` of zero, and it records its parent through `exchange_id`. Into a draft identification the coordinator adds **candidate properties**, each carrying a free-text `description` (a required string, accepted even when empty) and an `estimated_fmv` that must be strictly greater than zero; each candidate records the document it belongs to through `identification_id` and begins in `CANDIDATE` status. The identification's `aggregate_identified_fmv` is a derived field computed on demand as the sum of the `estimated_fmv` of every candidate under that identification whose status is still `CANDIDATE`, so adding a candidate changes the value the next read returns without re-stamping the parent identification — adding a candidate does not refresh the parent's `updated_at` or increment its `version` (only the new candidate is created). The exact count of those same `CANDIDATE` rows drives the breadth rules but is computed internally and is not surfaced as a field on the identification resource; the identification serializes `exchange_id`, `method`, `status`, `aggregate_identified_fmv`, and `finalized_at` alongside the common system fields, with no `candidate_count` field. Reading an identification returns its current `aggregate_identified_fmv`, and its candidates are independently listable.

Identification is finalized within the 45-day window, and finalization is where the breadth rules bite. Finalizing requires the parent exchange to be in `ACTIVE` status, at least one candidate still in `CANDIDATE` status to exist, the current clock to be on or before `id_deadline_at`, and no other identification on the same exchange to have already reached `FINALIZED`. A finalize attempted after `id_deadline_at` is rejected with `ERR_ID_DEADLINE_PASSED`. The two methods then diverge with equal force:

- Under the `THREE_PROPERTY` method, the document may be finalized only if it lists at most three candidates in `CANDIDATE` status, regardless of their values. A finalize with more than three candidates is rejected with `ERR_THREE_PROPERTY_RULE_VIOLATED`.
- Under the `TWO_HUNDRED_PCT` method, the document may be finalized only if the `aggregate_identified_fmv` is at most twice the relinquished property's `fair_market_value` — that is, the aggregate candidate value must not exceed 200% of the relinquished sale price. A finalize that breaches this cap is rejected with `ERR_TWO_HUNDRED_PCT_RULE_VIOLATED`.

A successful finalize stamps `finalized_at` to the current clock, sets the identification's `status` to `FINALIZED`, recomputes the parent exchange's posture to `IDENTIFIED` (the cascade from identification finalize to exchange posture), and increments the identification's `version`.

Should the taxpayer change course before committing, the coordinator may revoke a still-draft identification. Revocation is permitted only while the identification is in `DRAFT` status. It sets the identification's `status` to `REVOKED` and cascades downward, moving every child candidate currently in `CANDIDATE` status to `WITHDRAWN`, then increments the identification's `version`. A withdrawn candidate no longer contributes to any aggregate.

### 3.5. Acquiring Replacements and the Boot Calculation

Once an identification is finalized, the coordinator records each **replacement property** the taxpayer actually acquires. A replacement records the acquiring exchange through `exchange_id` and the satisfied candidate through `identified_property_id`, and carries a `purchase_price` strictly greater than zero, a `replacement_debt` of zero or greater representing new debt taken on the replacement, and an `improvement_value` of zero or greater that defaults to zero. The `improvement_value` is accepted (and stored) on a replacement of any exchange type, but it materially affects the calculation only for improvement exchanges; on a `FORWARD` or `REVERSE` replacement any supplied `improvement_value` is stored and echoed back yet ignored by the boot arithmetic. The candidate referenced by `identified_property_id` must be an `IdentifiedProperty` under *this* exchange's finalized identification whose status is still `CANDIDATE`; a reference to a candidate that is not under this exchange's finalized identification, or that has already been withdrawn, is rejected with `ERR_NOT_IDENTIFIED`. Because acquisition is a deadline-bound act, it must occur on or before `exchange_deadline_at`; an acquisition attempted after the 180-day deadline is rejected with `ERR_EXCHANGE_DEADLINE_PASSED`.

Recording a replacement stamps its `acquired_at` to the current clock, reclassifies the linked candidate's status from `CANDIDATE` to `ACQUIRED` (a downward cascade), and recomputes the exchange's gain figures before incrementing the exchange's `version`. The boot arithmetic runs in a pinned order — `cash_applied` first, then each boot leg, then the total boot, then recognized gain, then deferred gain — so that there is no circular dependency:

1. The **replacement value** depends on the exchange type. For a `FORWARD` or `REVERSE` exchange, the replacement value equals the `purchase_price` and any `improvement_value` is ignored entirely. For an `IMPROVEMENT` exchange the replacement value equals the `purchase_price` plus the `improvement_value`, which raises the cash applied and shrinks the cash boot relative to an otherwise identical forward case on the same `purchase_price`; the server does not separately track or condition on an improvement-completion date — every `IMPROVEMENT`-type replacement recorded within the 180-day window (the acquisition deadline gate that already governs this operation) adds its `improvement_value` to the replacement value.
2. The **cash applied** to the replacement — stored as `cash_applied` — is the replacement value less the `replacement_debt`.
3. The **cash boot** is the greater of zero and the trust's `deposited_amount` less the `cash_applied`; it can never be negative.
4. The **mortgage boot** is the greater of zero and the relinquished property's `mortgage_payoff` less the `replacement_debt`, representing net debt relief; the replacement debt offsets the relinquished debt, and the mortgage boot can never be negative.
5. The **total boot** is the sum of the cash boot and the mortgage boot.
6. The exchange's `recognized_gain` is the lesser of the exchange's `realized_gain` and the total boot.
7. The exchange's `deferred_gain` is the `realized_gain` less the `recognized_gain`, so that recognized and deferred gain always partition the realized gain exactly.

All seven steps round half up to two decimal places, and the `min`/`max` selections operate on two-decimal operands. Both `recognized_gain` and `deferred_gain` are null until the first replacement is recorded, then carry concrete values thereafter. A single replacement is fetchable on its own with its computed `cash_applied`, and replacements are listable both per exchange and globally with optional `exchange_id` and `identified_property_id` filters.

### 3.6. The Trust, the Disbursement Waterfall, and Four-Eyes Approval

The qualified trust is the conserved money pool of the exchange. Its `available_balance` is always the `deposited_amount` less the sum of the `amount` of every disbursement on the exchange whose `settlement_status` is `SETTLED`. Funds leave the trust only through disbursements, and disbursements are deliberately split between the coordinator who requests them and the settlement officer who approves them.

A `QICoordinator` creates a **disbursement** against an exchange's trust by supplying the `exchange_id`, a `purpose`, an `amount` strictly greater than zero, optionally a `replacement_property_id`, and the mandatory `expected_qualified_trust_version` described in §2.11. The `purpose` is one of `QI_FEE`, `ACQUISITION`, `IMPROVEMENT_DRAW`, or `BOOT_RETURN`, and from it the server derives a `priority` bucket — `QI_FEE` maps to 1, `ACQUISITION` to 2, `IMPROVEMENT_DRAW` to 3, and `BOOT_RETURN` to 4. The `replacement_property_id` identifies the replacement being funded and is meaningful only when the purpose is `ACQUISITION` or `IMPROVEMENT_DRAW`; it is null otherwise. A new disbursement begins in `REQUESTED` settlement status. If the named exchange has no qualified trust yet, the trust counts as an unresolved referenced resource and the create is rejected with `ERR_NOT_FOUND`. Creation is refused if the trust is locked, with `ERR_TRUST_LOCKED`, and — per §2.11 — refused with `ERR_STALE_TRUST_VERSION` when the supplied trust version is stale; the trust-lock check is evaluated before the version check, so a locked trust yields `ERR_TRUST_LOCKED` even when the supplied version is also stale. The priority buckets exist so that the waterfall is honored: lower-priority purposes are drawn first, and a `BOOT_RETURN` cannot overdraw funds already committed to higher buckets such as `QI_FEE` and `ACQUISITION`. This waterfall is not enforced as a separate ordering rule on approval; the `priority` value is a derived, informational label, and the only quantitative guard at approval is the sufficient-funds check (`amount` at most the current `available_balance`). Because each settled disbursement permanently reduces `available_balance`, a later `BOOT_RETURN` is naturally bounded by whatever higher-bucket disbursements have already settled, but disbursements may be approved in any order so long as each individually fits the available balance.

Approving a disbursement is the settlement officer's exclusive act and is where the money actually moves. Approval requires the disbursement to still be in `REQUESTED` settlement status, the parent exchange's `compliance_posture` to be `OPEN` or `IDENTIFIED`, the trust to be unlocked (`is_locked` false), the disbursement's `amount` to be at most the trust's current `available_balance`, and the approving operator to satisfy the four-eyes rule. These guards are checked in a fixed order: first the disbursement must be `REQUESTED` (a disbursement already `SETTLED` or `VOIDED` is rejected with `ERR_INVALID_STATE`); then the posture must be `OPEN` or `IDENTIFIED` — a non-approvable posture (`AT_RISK`, `COMPLETED`, or `FAILED`) is rejected with `ERR_TRUST_LOCKED` when the trust is locked (the usual case after completion or failure) and otherwise with `ERR_INVALID_STATE`; then, for a `BOOT_RETURN` purpose, at least one replacement property must already exist for the exchange (otherwise `ERR_INVALID_STATE`); then the segregation-of-duties check compares the approving officer's `X-User-ID` against the exchange's `coordinator_user_id`, and if they are the same operator the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`; then a locked trust is rejected with `ERR_TRUST_LOCKED`; and finally an amount exceeding the available balance is rejected with `ERR_INSUFFICIENT_TRUST_FUNDS`. Approval — moving the disbursement from `REQUESTED` to `SETTLED` — stamps the approving operator's identifier into `settlement_officer_user_id`, sets `settlement_status` to `SETTLED`, debits the trust's `available_balance` by the disbursement's `amount` (the cascade from disbursement settle to trust debit), and increments both the disbursement's `version` and the trust's `version`.

Voiding reverses a disbursement and behaves differently depending on where the disbursement stood. Voiding a disbursement that is currently `SETTLED` requires the trust to be unlocked — a void of a settled disbursement against a locked trust is rejected with `ERR_TRUST_LOCKED`; it moves the disbursement to `VOIDED`, credits the trust's `available_balance` back by the disbursement's `amount` as compensation that restores the conserved trust quantity, and increments both the disbursement's `version` and the trust's `version`. Voiding a disbursement that is still `REQUESTED` — one that was never debited — simply moves it to `VOIDED` with no trust effect and increments only the disbursement's `version`. In either path, a void on a disbursement not in a voidable state is rejected with `ERR_INVALID_STATE`. Disbursements are fetchable individually and listable with optional `exchange_id` and `replacement_property_id` filters.

### 3.7. Completing, Failing, and Terminating an Exchange

An exchange reaches its happy ending through completion, available to the coordinator. Completion requires the exchange's `compliance_posture` to be `IDENTIFIED`, every candidate under the finalized identification to have reached `ACQUIRED` status, the current clock to be on or before `exchange_deadline_at`, and both `recognized_gain` and `deferred_gain` to be non-null (meaning at least one replacement has been recorded). A completion from any posture other than `IDENTIFIED` is rejected with `ERR_INVALID_STATE`, and these guards are evaluated in order: first the exchange must be in `ACTIVE` status and its recomputed `compliance_posture` must be `IDENTIFIED` (otherwise `ERR_INVALID_STATE`), and only then is the on-or-before-`exchange_deadline_at` check applied (otherwise `ERR_EXCHANGE_DEADLINE_PASSED`). Because posture recomputation flips a finalized exchange to `AT_RISK` the instant the 180-day deadline passes, a completion attempted strictly after `exchange_deadline_at` is in practice rejected with `ERR_INVALID_STATE` (the posture is no longer `IDENTIFIED`) rather than reaching the deadline check. Completion recomputes the posture to `COMPLETED`, locks the qualified trust by setting `is_locked` to true (the cascade from exchange complete to trust lock), sets the exchange `status` to `COMPLETED`, and increments the exchange's `version`. A locked trust rejects all new disbursement creates and approvals.

When a deadline lapses irrecoverably the exchange fails. Failure may be driven by the coordinator or by the system when the clock advances past `exchange_deadline_at` before completion. It is permitted when the exchange is in `ACTIVE` status and either the current clock is past `exchange_deadline_at`, or no finalized identification exists and the current clock is past `id_deadline_at`. Failing recomputes the posture to `FAILED`, locks the trust (the cascade from exchange fail to trust lock), sets the exchange `status` to `FAILED`, and increments the exchange's `version`.

Finally, an exchange that never got off the ground may be terminated. Termination is permitted only while the exchange is in `DRAFT` status and only when no qualified trust on the exchange holds a positive `available_balance`. It sets the exchange `status` to `TERMINATED` and increments the exchange's `version`. Termination is a terminal lifecycle outcome, distinct from the deadline-driven `FAILED` end state.

### 3.8. Driving the Clock in Testing

To exercise the 45-day and 180-day behaviors deterministically, both the coordinator and the settlement officer may use an administrative test-driving capability that sets the server's logical clock to an absolute UTC instant supplied as `to_iso8601`. The `to_iso8601` field is required, must be a valid ISO 8601 instant (a trailing `Z` is accepted and treated as UTC), and a missing or unparseable value is rejected with `ERR_INVALID_REQUEST`. The capability returns `200 OK` and, because it produces no resource, an empty object in `data`. Advancing the clock causes subsequent posture reads to recompute against the new instant — which is how an exchange slides from `OPEN` toward `AT_RISK`, and how deadline-bound operations begin to reject with `ERR_ID_DEADLINE_PASSED` or `ERR_EXCHANGE_DEADLINE_PASSED` once the relevant instant is passed.

## 4. Endpoint Definitions

Operations that create a new, distinct resource (registering an exchanger, opening an exchange, attaching a property, opening a trust, adding a candidate, recording a replacement, or creating a disbursement) return a `201 Created` status code. Operations that modify or transition an existing resource (closing the relinquished leg, finalizing or revoking an identification, completing, failing, or terminating an exchange, approving or voiding a disbursement, and setting the clock) return a `200 OK` status code. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/exchangers` | Register a taxpayer principal | QICoordinator |
| GET | `/exchangers/{id}` | Fetch an exchanger | QICoordinator, SettlementOfficer, Exchanger |
| POST | `/exchanges` | Create an exchange in DRAFT; records the coordinator | QICoordinator |
| GET | `/exchanges/{id}` | Fetch an exchange with computed posture, deadlines, and gains | QICoordinator, SettlementOfficer, Exchanger |
| GET | `/exchanges` | List exchanges (paginated); filterable by exchanger | QICoordinator, SettlementOfficer |
| POST | `/exchanges/{id}/relinquished-properties` | Attach the relinquished property to a DRAFT exchange | QICoordinator |
| GET | `/exchanges/{id}/relinquished-properties` | List the relinquished property/properties for an exchange | QICoordinator, SettlementOfficer, Exchanger |
| POST | `/exchanges/{id}/trust` | Open the qualified trust for a DRAFT exchange | QICoordinator |
| GET | `/exchanges/{id}/trust` | List the qualified trust for an exchange | QICoordinator, SettlementOfficer, Exchanger |
| POST | `/exchanges/{id}/close-relinquished` | Close the relinquished leg; stamp Day-0, deposit, activate | QICoordinator |
| POST | `/exchanges/{id}/replacement-properties` | Record acquisition of a replacement property | QICoordinator |
| GET | `/exchanges/{id}/replacement-properties` | List replacement properties for an exchange | QICoordinator, SettlementOfficer, Exchanger |
| GET | `/replacement-properties/{id}` | Fetch a single replacement property | QICoordinator, SettlementOfficer, Exchanger |
| GET | `/replacement-properties` | List replacement properties (paginated); filterable | QICoordinator, SettlementOfficer |
| POST | `/exchanges/{id}/complete` | Mark the exchange COMPLETED | QICoordinator |
| POST | `/exchanges/{id}/fail` | Mark the exchange FAILED after a deadline lapse | QICoordinator |
| POST | `/exchanges/{id}/terminate` | Terminate a DRAFT exchange with no funded trust | QICoordinator |
| POST | `/exchanges/{id}/identifications` | Create a DRAFT identification on an ACTIVE exchange | QICoordinator |
| GET | `/exchanges/{id}/identifications` | List identifications for an exchange | QICoordinator, SettlementOfficer, Exchanger |
| GET | `/identifications/{id}` | Fetch an identification with computed aggregate | QICoordinator, SettlementOfficer, Exchanger |
| POST | `/identifications/{id}/candidates` | Add a candidate to a DRAFT identification | QICoordinator |
| GET | `/identifications/{id}/candidates` | List candidate properties under an identification | QICoordinator, SettlementOfficer, Exchanger |
| POST | `/identifications/{id}/finalize` | Finalize the identification within the 45-day window | QICoordinator |
| POST | `/identifications/{id}/revoke` | Revoke a DRAFT identification; withdraw its candidates | QICoordinator |
| POST | `/disbursements` | Create a REQUESTED disbursement (OCC-guarded) | QICoordinator |
| GET | `/disbursements/{id}` | Fetch a disbursement | QICoordinator, SettlementOfficer, Exchanger |
| GET | `/disbursements` | List disbursements (paginated); filterable | QICoordinator, SettlementOfficer |
| POST | `/disbursements/{id}/approve` | Approve a REQUESTED disbursement; debit the trust | SettlementOfficer |
| POST | `/disbursements/{id}/void` | Void a disbursement; credit the trust if it was settled | SettlementOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | QICoordinator, SettlementOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ID_DEADLINE_PASSED` | 409 Conflict |
| `ERR_EXCHANGE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_THREE_PROPERTY_RULE_VIOLATED` | 409 Conflict |
| `ERR_TWO_HUNDRED_PCT_RULE_VIOLATED` | 409 Conflict |
| `ERR_NOT_IDENTIFIED` | 409 Conflict |
| `ERR_TRUST_LOCKED` | 409 Conflict |
| `ERR_INSUFFICIENT_TRUST_FUNDS` | 409 Conflict |
| `ERR_STALE_TRUST_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_TAXPAYER_ID` | 409 Conflict |
| `ERR_TRUST_ALREADY_EXISTS` | 409 Conflict |
