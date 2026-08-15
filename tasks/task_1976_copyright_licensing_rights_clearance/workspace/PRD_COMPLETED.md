# Copyright Rights Clearance API — Product Requirements Document

## 1. Introduction

A media rights and clearances desk exists to answer one deceptively simple question: may this work be used, in this way, in this place, for this long — and at what price? The desk shepherds creative works — musical compositions, sound recordings, film clips, still images, and literary excerpts — from intake to licensed use. Producers and editors request clearance for a particular medium, territory, and term; desk officers identify and verify rights holders, conducting documented diligence when a work appears to be orphaned; negotiators and rights-holder representatives trade fee offers under strict alternation rules; finance operators settle the agreed fee; ingestion pipelines report actual consumption against licensed unit limits; and attorneys handle fair-use certification and DMCA takedown response. Eventually, every asset is retired from circulation.

This document specifies a REST API, mounted under `/rights`, that implements that desk end to end. Several design commitments shape everything that follows. Asset **posture** is never set directly — it is derived from takedowns, licenses, and orphan status, and its transitions cascade into licenses, reservations, and alerts. Every license carries two parallel state dimensions, a lifecycle and a fee status, which move independently. Usage is accounted twice, gross and net, because takedown remedies can strike past consumption. Segregation of duties is enforced across eight roles so that no operator can request and approve, pay, or certify the same item. Three write paths are guarded by optimistic concurrency. And all time-driven behavior — embargo gates, counter-notice windows, reservation holds, term expirations, renewal alerts — is governed by a controllable logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. The role header must contain exactly one of the eight declared role names, spelled as follows:

- `Requester` — a producer or editor requesting clearance for an asset.
- `ClearanceOfficer` — a desk officer who advances or denies clearance requests and grants licenses.
- `Negotiator` — a fee negotiator who posts and accepts negotiation rounds.
- `FinancePayer` — a finance operator who posts license payments and refunds.
- `IngestionAgent` — a systems agent that reserves usage units and posts usage events.
- `LegalCertifier` — an attorney who certifies fair-use assessments and revokes licenses.
- `AssetCurator` — the rights-desk curator who manages assets, rights holders, diligence records, takedown notices, and the logical clock.
- `RightsHolderRep` — an external rights-holder representative who participates in fee negotiation.

A request that is missing `X-User-Role`, carries an undeclared role value, or is missing `X-User-ID` — under any role, entity-backed or opaque — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose declared role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity semantics differ across the roster. When `X-User-Role` is `RightsHolderRep`, `X-User-ID` is the `id` of the acting RightsHolder — the representative operates on behalf of a persisted holder record — though the id is accepted as presented, never resolved against persisted RightsHolder records at request time — and ownership checks on any resource that references a RightsHolder compare the resource's foreign-key field to `X-User-ID`. For `Requester`, `ClearanceOfficer`, `Negotiator`, `FinancePayer`, `IngestionAgent`, `LegalCertifier`, and `AssetCurator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow requires an actor anchor — for example as `requester_id` on a clearance request or `payer_id` on a license payment — and ownership or segregation checks compare the header against those recorded fields, but it is never compared to any entity's `id`.

Segregation of duties runs through the whole desk. The requester who created a clearance request may not accept a fee round on it, may not pay its license, and may not certify its fair-use assessment; those actions belong to other hands, and violations surface as `ERR_SEGREGATION_OF_DUTIES` at the workflow steps described in §3.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0. A `limit` that is not an integer, is below 1, or exceeds 100, and an `offset` that is not an integer or is negative, are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object; `has_more` is true exactly when `offset` plus the size of the returned page is still below `total_count`. Lists are sorted by `created_at` in ascending order unless stated otherwise, with ties on `created_at` falling back to creation order.

### 2.4. Resource Identity and Common Properties

Every persisted resource carries an `id` — a server-minted UUID with no type prefix. Assets, rights holders, clearance requests, licenses, usage reservations, fair-use assessments, takedown notices, and renewal alerts additionally carry the common audit triple: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, plus `version`, an integer that increments on every mutation of the resource. Every datetime the server emits uses that same wire format — not only the audit triple, but operational instants such as `embargo_until`, `retired_at`, `use_start_at`, `use_end_at`, `term_start_at`, `term_end_at`, `hold_expires_at`, `used_at`, `posted_at`, `received_at`, `counter_notice_due_at`, and `fires_at`, as well as ledger rows' `created_at` and the clock response's `current_utc`.

Four record types are append-only ledger entries and deliberately carry less. Rights diligence logs, negotiation rounds, usage events, and license payments carry only `id` and `created_at`; both `updated_at` and `version` are absent from these records, because they are never modified after creation — later activity appends new rows rather than rewriting history.

### 2.5. The Desk's Logical Clock

Time inside the system is a logical clock, not the wall clock. Before any clock-setting call has been made, the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. An `AssetCurator`-only capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. The supplied instant is adopted unconditionally — there is no monotonicity check, so the clock may be moved backward as well as forward.

Setting the clock is never a passive read: each advance evaluates every clock-driven transition in the desk — the clearance-request expiry sweep, the reservation forfeiture sweep, the takedown counter-window lapse sweep, the license expiry sweep, the renewal-alert firing sweep, and the asset posture recompute that any of these may trigger. All datetime comparisons in this system are made at second precision.

### 2.6. Monetary Precision and Rounding

All monetary values are integer cents. Fee arithmetic is computed in floating point and rounded half-up to integer cents exactly once, at the final step of the fee recipe. Per-component rounding is explicitly rejected: a license carries exactly one fee line, and rounding intermediate components before combining them would diverge by whole cents. Territory weights are exact to one decimal place. Usage quantities (`units`, `requested_units`, reservation and event amounts) are whole units throughout — a unit is one exhibition, stream, or thousand impressions depending on the medium, and fractional units do not exist.

### 2.7. Optimistic Concurrency Control

Three write paths carry an optimistic-concurrency guard, and only these three. Advancing a clearance request requires the request body to carry `expected_clearance_version`, holding the request's `version` as the client last observed it. Posting a license payment requires `expected_license_version`, holding the license's current `version` as last read. Creating a usage reservation likewise requires `expected_license_version` for the parent license.

In each case, if the parent entity's `version` has advanced beyond what the client last observed — because another officer has advanced or re-routed the request, a prior payment has moved the fee status, or another reservation has already shrunk the unit pool — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the parent entity before retrying. Endpoints not named in this section do not take a version field at all.

### 2.8. Validation Priority Ladder

Unless a specific workflow pins its own ordering (§3 does so for clearance advancement, round acceptance, license grant, withdrawal, and the fair-use workflow), every request is validated against the following ladder, evaluated top to bottom; a failure at any rung masks every rung below it.

1. **Authentication** — `X-User-Role` present and declared, `X-User-ID` present (required under every role); failure is `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization** — the declared role is permitted on the endpoint; failure is `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Path existence** — path resources exist, validated left to right; failure is `ERR_NOT_FOUND` (HTTP 404).
4. **Request-body schema** — required fields present, enum values in range, datetimes well-formed, integer fields at or above their minimums; failure is `ERR_INVALID_REQUEST` (HTTP 400).
5. **Optimistic concurrency** — the expected-version field matches the parent entity's current `version`; failure is `ERR_STALE_VERSION` (HTTP 412).
6. **Transition legality** — the target resource is in a state from which the requested transition exists; failure is `ERR_INVALID_STATE` (HTTP 409).
7. **DMCA and takedown safety gates** — counter-notices inside their window, revocations backed by an upheld notice, new clearance work only on unblocked assets; failures include `ERR_COUNTER_WINDOW_LAPSED`, `ERR_NO_UPHELD_TAKEDOWN`, and `ERR_ASSET_POSTURE_BLOCKED` (HTTP 409). Applies to takedown counter, license revoke, and clearance advance or grant.
8. **Referential integrity** — rights holder resolvable or the asset orphan-certified before negotiation; requested media within the asset's permitted set; a fair-use assessment's referenced request valid; failures include `ERR_RIGHTS_HOLDER_UNIDENTIFIED`, `ERR_MEDIA_NOT_PERMITTED`, `ERR_FAIR_USE_MEDIA_INELIGIBLE`, and `ERR_ORPHAN_DILIGENCE_INCOMPLETE` (HTTP 409). Applies to clearance advance and fair-use creation.
9. **Temporal rules** — use windows well-formed, embargo gates, usage inside the license term, holds unexpired at consumption, grant windows non-overlapping; failures include `ERR_INVALID_WINDOW`, `ERR_EMBARGO_ACTIVE`, `ERR_USAGE_OUTSIDE_TERM`, `ERR_HOLD_EXPIRED`, and `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 422, except `ERR_HOLD_EXPIRED`, which is HTTP 409 per §5). Applies to clearance creation and advance, usage-event posting, and grant.
10. **Constraint rules** — negotiation round caps and role alternation, reservation and event draw-down bounds, one license per request; failures include `ERR_NEGOTIATION_EXHAUSTED`, `ERR_ROUND_ROLE_ALTERNATION`, `ERR_USAGE_OVERDRAW`, `ERR_QUOTA_EXCEEDED`, and `ERR_LICENSE_ALREADY_EXISTS` (HTTP 409). Applies to rounds, reservations, usage events, and grant.
11. **Fiscal rules** — the most-favored-nation floor at acceptance, overpayment rejection, refund eligibility, segregation of duties on approval, payment, and certification; failures include `ERR_MFN_FLOOR_VIOLATION`, `ERR_OVERPAYMENT`, `ERR_REFUND_REQUIRES_TERMINAL`, `ERR_REFUND_AFTER_USE`, `ERR_SEGREGATION_OF_DUTIES`, and `ERR_LICENSE_NOT_PAYABLE` (HTTP 422). Applies to round acceptance, payments, and certification.

### 2.9. Derived Asset Posture and Cascade Consistency

An asset's `posture` is a computed field, never set directly by any request. It re-derives whenever anything touching the asset changes — a takedown notice created or transitioned, a license granted or moving lifecycle, a diligence log appended, or `orphan_status` changing. The derivation is a fixed precedence chain, evaluated top to bottom with first match winning:

1. If `retired_at` is set, the posture is `RETIRED`.
2. If any takedown notice on the asset is `UPHELD`, the posture is `SUSPENDED`.
3. If any takedown notice on the asset is `PENDING` and the clock has moved strictly later than its `counter_notice_due_at`, the posture is `SUSPENDED`.
4. If the asset's `orphan_status` is `DILIGENCE_PENDING`, the posture is `ENCUMBERED`.
5. If any takedown notice on the asset is `PENDING` and still inside its counter window, the posture is `ENCUMBERED`.
6. If any license on the asset has `lifecycle` `ACTIVE` with territory `WORLD`, the posture is `ENCUMBERED`.
7. Otherwise the posture is `CLEAR`.

Posture transitions are consistency events in their own right. When a posture moves into `SUSPENDED`, every license on the asset whose `lifecycle` is `ACTIVE` is cascade-suspended — moved to `SUSPENDED` and marked with `suspension_cause` of `TAKEDOWN` — carrying its own reservations and alerts down with it per §3.7. When the posture moves back out of `SUSPENDED`, exactly those cascade-suspended licenses return to `ACTIVE`; nothing else is restored. Any posture transition refreshes the asset's `updated_at` and bumps its `version`.

The same touch-propagation discipline applies throughout the tree: round acceptance, license grant, and fair-use rerouting each refresh the parent asset (version bump, `updated_at` refresh), so a reader watching the asset always sees that something underneath it moved.

### 2.10. Nested Retrieval, Filtering, and Worklists

Parameterized paths are validated left to right, each identifier within the scope of its parent: the asset before the clearance request, the clearance request before its rounds, the license before its reservations, payments, usage events, and alerts. A miss at any point in the chain is `ERR_NOT_FOUND` (HTTP 404), regardless of whether a like-named identifier exists elsewhere in the system.

List endpoints double as desk worklists and accept optional filters alongside `limit` and `offset`. The asset list filters by `posture` and `rights_holder_id`. The cross-asset clearance-request worklist filters by `status` and `fair_use_assessment_id`; the per-asset request list filters by `status`. The license list filters by `asset_id`, `clearance_request_id`, `renewal_alert_id`, `lifecycle`, and `fee_status`. Reservation lists, takedown lists, fair-use lists, and renewal-alert lists each filter by `status`, and the cross-asset fair-use list additionally filters by `clearance_request_id`.

## 3. Business Logic & Workflows

### 3.1. Rights Holders, Asset Registration, and Orphan-Work Diligence

Before any work can be cleared, the desk needs to know what the work is and who owns it. An `AssetCurator` registers a rights holder with a `legal_name`, a `holder_kind` of `PUBLISHER`, `LABEL`, `ESTATE`, `COLLECTIVE`, or `INDIVIDUAL`, and an `mfn_floor_cents`, a non-negative integer of cents — a most-favored-nation floor declaring that no license paying this holder may price below that per-unit amount, unless the holder is an `ESTATE`. Registration may also record `contact_verified`, a boolean that defaults to false when omitted.

Asset registration, also by an `AssetCurator`, captures the `title`; the `work_kind`, one of `MUSICAL_COMPOSITION`, `SOUND_RECORDING`, `FILM_CLIP`, `STILL_IMAGE`, or `LITERARY_EXCERPT`; and the `permitted_media` list, a non-empty subset of `BROADCAST_TV`, `STREAMING`, `THEATRICAL`, `RADIO`, `SOCIAL`, and `PRINT` that bounds what the asset can ever be cleared for — uses outside this set are never clearable. An optional `embargo_until` (absent by default) embargoes the work: the asset cannot be licensed for any use beginning earlier than thirty days after that instant. An optional `rights_holder_id` links the work to its holder; it stays null while the holder is unidentified, and a supplied `rights_holder_id` that resolves to no registered holder is rejected with `ERR_NOT_FOUND` (HTTP 404). A newly registered asset enters with posture `CLEAR` and `retired_at` null; its `orphan_status` is set to `NOT_ORPHAN` when a `rights_holder_id` is supplied at registration and to `DILIGENCE_PENDING` otherwise. Registration itself does not run the §2.9 derivation — a holderless asset is therefore born `CLEAR` even while its `orphan_status` is `DILIGENCE_PENDING`, and the precedence chain first governs that asset's posture at the next re-derivation trigger.

When no holder is known, the desk documents its search. Appending a diligence record — again an `AssetCurator` action, with `asset_id` taken from the path — captures a `search_channel` of `COPYRIGHT_OFFICE`, `PERFORMING_RIGHTS_ORG`, `UNION_GUILD`, `COMMERCIAL_DATABASE`, or `DIRECT_OUTREACH`; an `outcome` of `HOLDER_FOUND`, `NO_RESULT`, or `CONFLICTING_CLAIM`; and free-text `notes`. Orphan certification is mechanical: when the asset's `rights_holder_id` is null, at least three diligence logs exist with pairwise distinct `search_channel` values, every diligence log in the asset's history — not merely the qualifying three — has `outcome` `NO_RESULT` (a single `HOLDER_FOUND` or `CONFLICTING_CLAIM` anywhere in the history blocks certification), and the span between the first and last qualifying log's `created_at` is at least thirty days, the asset's `orphan_status` becomes `ORPHAN_CERTIFIED`, and that change triggers a posture recompute under §2.9. Diligence history is readable by the curator, desk officers, and legal certifiers.

### 3.2. Clearance Request Intake and Routing

A `Requester` opens a clearance request against a registered asset by supplying the `media` sought (one of the six media kinds), the `territory` (`NA`, `EMEA`, `LATAM`, `APAC`, or `WORLD`), a `use_start_at` and `use_end_at` bounding the use window, and the `requested_units` of consumption sought. The window is half-open: the start is inclusive, the end exclusive, and `use_end_at` must fall strictly after `use_start_at` — a zero-length or inverted window is rejected with `ERR_INVALID_WINDOW`. The embargo gate applies here, at creation: if the asset carries an `embargo_until`, the `use_start_at` must be on or after the instant thirty days past it; equality passes, anything earlier is rejected with `ERR_EMBARGO_ACTIVE`. The creating header is recorded as `requester_id`, and the request is born in `SUBMITTED` with `negotiation_round` at 0.

From there a `ClearanceOfficer` advances the request along `SUBMITTED` → `HOLDER_REVIEW` → `NEGOTIATING`, one step per call, with the OCC guard of §2.7: the body must carry `expected_clearance_version` matching the request's current `version`, and each successful advance increments that `version` by 1. The first step, into `HOLDER_REVIEW`, evaluates three gates in a pinned order. The orphan-diligence gate comes first: an `orphan_status` of `DILIGENCE_PENDING` rejects with `ERR_ORPHAN_DILIGENCE_INCOMPLETE`, and an `ORPHAN_CERTIFIED` asset passes this gate only while its `rights_holder_id` is still null. The media gate comes second: the request's `media` must be among the asset's `permitted_media`, else `ERR_MEDIA_NOT_PERMITTED`. The posture gate comes last — deliberately after the orphan gate, so the more specific diligence diagnosis wins over the blunter `ERR_ASSET_POSTURE_BLOCKED`, which fires whenever the posture is anything other than `CLEAR`. The embargo gate is also re-evaluated at this first advance. The second step, from `HOLDER_REVIEW` into `NEGOTIATING`, requires that someone is there to negotiate with: the asset's `rights_holder_id` must be set, or the asset must be `ORPHAN_CERTIFIED` — otherwise `ERR_RIGHTS_HOLDER_UNIDENTIFIED`. On entry to `NEGOTIATING` the `negotiation_round` remains 0 and the first fee round may be posted.

Officers may also close requests out. Denial is available from `SUBMITTED`, `HOLDER_REVIEW`, or `NEGOTIATING`; from `NEGOTIATING` it requires that every round already be resolved, and any round still `OPEN` is automatically moved to `REJECTED` as the denial lands. Withdrawal is the requester's own exit: withdrawal is permitted from `SUBMITTED`, `HOLDER_REVIEW`, or `NEGOTIATING` — the state check runs first, so an attempt on an already-closed request is `ERR_INVALID_STATE` regardless of caller — and the calling header must then equal the recorded `requester_id`, another user's attempt being `ERR_FORBIDDEN_OWNER_ONLY`; leaving `NEGOTIATING` rejects any `OPEN` rounds. Both `DENIED` and `WITHDRAWN` are terminal.

Two reroutings bypass the commercial path. A requester may take the fair-use route described in §3.8, which moves a `SUBMITTED` request to the terminal `FAIR_USE_ROUTE` state and records the assessment under `fair_use_assessment_id`. And the clock closes stale work: a request still in `SUBMITTED` when the clock reaches its `use_end_at` expires to `EXPIRED`, and an `APPROVED` request whose grant was never executed expires the same way when its window runs out.

### 3.3. Fee Estimation and Negotiation Rounds

Every fee the desk computes follows one pinned recipe. The **base** is the per-media unit rate multiplied by `requested_units`; the unit rates, in cents, are 50,000 for `BROADCAST_TV`, 80,000 for `THEATRICAL`, 12,000 for `STREAMING`, 5,000 for `PRINT`, 8,000 for `RADIO`, and 3,000 for `SOCIAL`. The **territory multiplier** weights the footprint: `NA` at 1.0, `LATAM` at 0.8, `APAC` at 1.2, `EMEA` at 1.4, and `WORLD` at 3.0. The **term multiplier** reads the whole-day length of the requested window: at most ninety days multiplies by 1.0, longer than ninety days and at most three hundred sixty-five days multiplies by 1.25, and anything longer multiplies by 1.6. The raw fee is the base times the territory multiplier times the term multiplier. A bulk discount applies only when `requested_units` is at least one hundred: the raw fee is reduced by ten percent. The result is rounded half-up to integer cents — exactly once, at this final step, per the precision contract of §2.6 — and the most-favored-nation floor is applied last, after rounding, as the greater of the rounded raw fee and the floor.

This recipe has two variants. When a request enters `NEGOTIATING`, the desk computes a **provisional estimate** as guidance for the negotiator alone: the MFN floor is not applied, since the holder may counter below the displayed floor. The **final fee** is computed at round acceptance, and there the floor is a hard validation rather than a display nicety. The floor itself is zero for an `ESTATE` holder — estates are exempt — and for every other holder kind it is the holder's `mfn_floor_cents` multiplied by the request's `requested_units`.

Negotiation proceeds in rounds posted by a `Negotiator` or a `RightsHolderRep`, each carrying an `offered_fee_cents`, a non-negative integer of cents, and an optional `accept` flag that defaults to false when omitted. Rounds are numbered by a `round_index` that starts at 1 and climbs monotonically per request, and each round's `offered_by_role` is derived from the caller's role — `NEGOTIATOR` for a `Negotiator`, `RIGHTS_HOLDER_REP` for a `RightsHolderRep`. Two constraints discipline the exchange. First, the cap: a request completes at most five rounds, and an attempt at a sixth is rejected with `ERR_NEGOTIATION_EXHAUSTED`. Second, alternation: the new round's `offered_by_role` must differ from the most recently persisted round's `offered_by_role` — the two sides trade offers, never speaking twice in a row — with violation rejected as `ERR_ROUND_ROLE_ALTERNATION`; the very first round may be opened by either role. A round submission that fails any validation persists no row at all, so the round history contains only rounds that passed every check. Each successfully posted round supersedes its predecessor — the prior `OPEN` round's `outcome` becomes `SUPERSEDED` — and the request's `negotiation_round`, the count of completed fee rounds, increments by 1. A round's `outcome` is one of `OPEN`, `ACCEPTED`, `REJECTED`, or `SUPERSEDED`. The rounds list endpoint returns them ordered by `round_index`, not by the default `created_at` sort of §2.3.

Acceptance happens when a round is posted with `accept` set true. Its checks run in a pinned order: the alternation rule first, then the MFN floor, then segregation of duties. The accepted round's `offered_fee_cents` must be at least the floor, else `ERR_MFN_FLOOR_VIOLATION` — unless, again, the holder is an `ESTATE`. And the accepting operator must not be the person who asked for the clearance: the acceptor's `X-User-ID` is compared against the request's `requester_id`, and a match is `ERR_SEGREGATION_OF_DUTIES`. On acceptance the round's `outcome` becomes `ACCEPTED`, the request moves `NEGOTIATING` → `APPROVED`, its `agreed_fee_cents` is set to the accepted `offered_fee_cents`, and the parent asset is cascade-touched with a version bump.

### 3.4. License Grant and the Rights Window

Granting turns an `APPROVED` request into a license; it is a `ClearanceOfficer` action and creates a new resource. Three things must line up. The supplied `grant_fee_cents`, a non-negative integer of cents, must equal the request's `agreed_fee_cents` exactly — any drift is `ERR_FEE_MISMATCH`. The asset's posture must be `CLEAR`, else `ERR_ASSET_POSTURE_BLOCKED`. And the new rights window must not collide with an existing one: the grant is rejected with `ERR_LICENSE_WINDOW_OVERLAP` when any other license on the same asset has `lifecycle` `ACTIVE`, the same `media`, an overlapping territory, and an intersecting term. Territory overlap follows superset semantics — `WORLD` contains every territory, so it overlaps all of them, and two non-`WORLD` territories overlap only when equal. Term intersection uses half-open windows: the existing term must start strictly before the new term's end, and the new term must start strictly before the existing term's end; a merely adjacent window, where the existing `term_end_at` is exactly the new `term_start_at`, does not conflict because term ends are exclusive. Finally, a request yields at most one license — a second grant against the same request is `ERR_LICENSE_ALREADY_EXISTS`.

The granted license copies its shape from the request: `clearance_request_id` and a denormalized `asset_id` (kept so the posture cascade of §2.9 can find the license from the asset); `territory` and `media` copied verbatim; `term_start_at` taken from the request's `use_start_at` as an inclusive bound and `term_end_at` from its `use_end_at` as an exclusive one; `unit_limit` set to `requested_units`; and `fee_agreed_cents` set to `agreed_fee_cents`. It is born with `lifecycle` `ACTIVE` and `fee_status` `UNPAID`, and its consumption counters `units_reserved`, `units_consumed_net`, and `units_consumed_gross` are computed fields that derive from its reservations and events per §3.5. The grant also schedules the license's renewal alert: a `RenewalAlert` in `SCHEDULED` whose `fires_at` is thirty days before `term_end_at`, linked from the license as `renewal_alert_id`. The request itself moves to the terminal `LICENSED` state, and the asset's `updated_at` refreshes with a version bump.

Two parallel dimensions govern a license from that moment on. The **lifecycle** dimension walks `ACTIVE`, `SUSPENDED`, `EXPIRED`, and `REVOKED`; the **fee status** dimension walks `UNPAID`, `PARTIALLY_PAID`, `PAID`, and `REFUNDED`. Transitions on one dimension do not move the other except where this document says so explicitly. `EXPIRED` and `REVOKED` are the terminal lifecycle states — though even a terminal license's fee status may still move to `REFUNDED` through the compensation path of §3.6.

### 3.5. Usage Reservations and Consumption Accounting

Licenses meter consumption in whole units, and the desk tracks the pool three ways. `units_consumed_gross` sums the `units` of every usage event on the license whose `posting_kind` is `POSTED`, ignoring later strikes; `units_consumed_net` subtracts from that total the `units` of events whose `posting_kind` is `STRUCK`; and `units_reserved` sums the `units` of reservations still `HELD`. The units available for new reservation are what's left: `unit_limit` minus `units_reserved` minus `units_consumed_net`. Gross consumption feeds refund eligibility and royalty reporting — struck usage still counted, because the use happened — while net consumption feeds reservation admission and renewal-utilization views, so a revocation cascade that strikes past events can legitimately lower net and free availability.

An `IngestionAgent` reserves units by posting the desired `units` — at least one — against a license, under the OCC guard of §2.7 (`expected_license_version`). The license's `lifecycle` must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`, and admission requires the requested `units` to be at most the units available; requesting exactly the available amount succeeds, one more is rejected with `ERR_QUOTA_EXCEEDED`. A fresh reservation is `HELD`, with `license_id` taken from the path and `hold_expires_at` stamped at seven hundred twenty hours — thirty days — after its `created_at`. The license's `units_reserved` rises by the reserved amount and the license's `version` increments by 1.

Reservations leave `HELD` three ways. Consumption draws them down (below). Release is a deliberate `IngestionAgent` action that moves a hold to `RELEASED` and returns its units to the pool; release also refreshes the parent license with a version bump and `updated_at` refresh. Forfeiture is the clock's: when the clock reaches `hold_expires_at`, the hold moves to `FORFEITED` and its units return to availability, and unlike release the forfeiture sweep touches only the reservation row, leaving the license's `version` unchanged. Forfeits are permanent — a license that is later reactivated never gets its forfeited reservations back.

Usage events record what actually ran. An `IngestionAgent` posts `units` — again at least one — and a `used_at` instant, optionally naming a `reservation_id`. When a reservation is referenced, the draw-down path applies: the license must be `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE` otherwise); the referenced reservation must exist under this license — a missing or foreign `reservation_id` is `ERR_NOT_FOUND` — and must still be `HELD`, else `ERR_INVALID_STATE`; the reservation must still be within its hold — consumption at or after `hold_expires_at` is `ERR_HOLD_EXPIRED`; the event's `units` must be at most the reservation's remaining `units`, with an excess rejected as `ERR_USAGE_OVERDRAW`; and `used_at` must fall inside the license term — on or after `term_start_at` and strictly before `term_end_at`, else `ERR_USAGE_OUTSIDE_TERM`. The effects of a successful draw: the license's `units_reserved` falls by the event's `units`, both `units_consumed_gross` and `units_consumed_net` rise by the same amount, and the reservation either stays `HELD` with its `units` reduced by the event's amount (a partial draw) or, when the event exactly empties it, moves to `CONSUMED`. When `reservation_id` is omitted, the event is **direct-grant usage**: no reservation bookkeeping applies, but the license must still be `ACTIVE` and `used_at` must still fall inside the term. Every usage event is born with `posting_kind` `POSTED`; a later takedown remedy can restamp it `STRUCK` per §3.7. Each posted event also bumps the license's `version`.

### 3.6. Fee Settlement: Payments, Refunds, and Fee Status

Settlement is the `FinancePayer`'s desk. Each posting carries an `amount_cents` — a non-zero integer, positive for a payment, negative for a refund; a zero or non-integer amount is `ERR_INVALID_REQUEST` (HTTP 400) — plus the OCC guard `expected_license_version`; the server records the caller as `payer_id` and stamps `posted_at` itself. A positive payment is accepted only while the license's `lifecycle` is `ACTIVE`; posting against a suspended, expired, or revoked license fails with `ERR_LICENSE_NOT_PAYABLE`. Segregation of duties applies here as everywhere: the payer's `X-User-ID` must differ from the originating request's `requester_id`, else `ERR_SEGREGATION_OF_DUTIES`; the check applies to refunds as well as payments and runs immediately after the OCC check, before the payable, overpayment, and refund-eligibility rules below. Overpayment is rejected outright — a payment that would push the cumulative paid total above `fee_agreed_cents` fails with `ERR_OVERPAYMENT` before any status recomputation runs. Each accepted payment increments the license's `version` by 1.

The `fee_status` is recomputed from the ledger after every posting. Let the cumulative total be the sum of all `amount_cents` on the license, refunds counting negative. If the total is zero or negative and at least one payment row exists, the status is `REFUNDED`. If the total is exactly zero with no rows at all, it is `UNPAID`. Below `fee_agreed_cents` it is `PARTIALLY_PAID`; exactly equal, `PAID`. The fee dimension therefore walks `UNPAID` → `PARTIALLY_PAID` on a partial payment, `UNPAID` → `PAID` on full payment, `PARTIALLY_PAID` → `PAID` when the cumulative total reaches the agreed fee, and onward to `REFUNDED` from either paid state.

Refunds follow the mirror image of payment rules. A refund requires a terminal lifecycle — `EXPIRED` or `REVOKED` — and anything else is `ERR_REFUND_REQUIRES_TERMINAL`. It also requires that nothing was ever used: `units_consumed_gross` must be zero, and a license with any posted usage, even usage later struck by a takedown remedy, refuses the refund with `ERR_REFUND_AFTER_USE`. From `PAID`, only a full refund is accepted — the negative `amount_cents` must exactly match `fee_agreed_cents` in magnitude. From `PARTIALLY_PAID`, the refund must exactly cancel the cumulative amount paid to date. A refund whose magnitude does not exactly cancel the cumulative paid total is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.7. Takedown Notices, Suspension Cascades, and License Revocation

When a DMCA claim lands, an `AssetCurator` files a takedown notice with the `claimant_name`; the server stamps `received_at` from the logical clock and sets `counter_notice_due_at` ten days later. The notice is born `PENDING`, and its arrival already shifts the ground: the posture recompute of §2.9 reads a live `PENDING` notice as `ENCUMBERED` while its counter window runs.

The desk answers a notice by countering it. Countering is an `AssetCurator` action available only while the clock is strictly earlier than `counter_notice_due_at`; at exactly the deadline the window has already lapsed, and the counter fails with `ERR_COUNTER_WINDOW_LAPSED`. A successful counter moves the notice `PENDING` → `COUNTERED` and triggers a fresh posture recompute. If instead the clock moves strictly later than `counter_notice_due_at` with no counter filed, the notice flips from `PENDING` to `UPHELD` on its own, and the full cascade fires: the asset's posture becomes `SUSPENDED`, every `ACTIVE` license on the asset moves to `SUSPENDED` (marked with `suspension_cause` `TAKEDOWN`), every reservation those licenses hold in `HELD` is moved to `FORFEITED`, and every renewal alert still `SCHEDULED` under them is `CANCELLED`.

A claimant may retract at any point — from `PENDING`, from `COUNTERED`, and even from `UPHELD`, which is deliberately not a terminal state; `RETRACTED` is the only terminal state a notice has. Retraction recomputes the asset's posture — typically `SUSPENDED` back to `CLEAR` when no other upheld or lapsed notice remains — and every license that the takedown cascade suspended returns to `ACTIVE`. What does not come back: forfeited reservations stay forfeited, permanently. Where the returned license's renewal alert was cancelled, a replacement alert is created in `SCHEDULED` with its computed `fires_at`, provided that instant is still in the future. This retraction path is the only way a cascade-suspended license ever stands back up.

Revocation is the legal remedy on top of an upheld claim. A `LegalCertifier` may revoke a license from `ACTIVE` or from `SUSPENDED`, but only while some takedown notice on the asset stands `UPHELD` — otherwise `ERR_NO_UPHELD_TAKEDOWN`. Revocation forfeits any reservations still `HELD` (a suspended license has already lost them), cancels the license's `SCHEDULED` renewal alert, and strikes the usage record: every usage event whose `posting_kind` is `POSTED` and whose `used_at` falls on or after the notice's `received_at` is restamped `STRUCK` — where several notices stand `UPHELD`, the strike window keys off the earliest `received_at` among them. The license's `units_consumed_net` is then recomputed and may drop, freeing availability under §3.5's accounting; `units_consumed_gross` is untouched — the use happened, even if the remedy erases its count against the limit.

### 3.8. Fair Use Assessment and Certification

Not every use needs a negotiated license. A `Requester` may instead file a fair-use assessment on an asset, naming a `clearance_request_id` that must reference a request on that same asset — an id that resolves to no request on the asset is `ERR_NOT_FOUND` (HTTP 404) — and still in `SUBMITTED`, else `ERR_INVALID_STATE`, and supplying `factor_scores` — an object with `purpose`, `nature`, `amount`, and `market`, each an integer from 1 to 4 scoring one factor of the four-factor test. The route is narrow: only `SOCIAL` or `PRINT` media are eligible, and any other medium is rejected with `ERR_FAIR_USE_MEDIA_INELIGIBLE`; this media gate is evaluated before the `SUBMITTED`-state check, so an ineligible medium wins over `ERR_INVALID_STATE`. Filing reroutes the linked request `SUBMITTED` → `FAIR_USE_ROUTE`, terminal, with the commercial path closed permanently; the request's `fair_use_assessment_id` is set to the new assessment, and the asset takes a version bump. If an earlier assessment for the same request is still in `DRAFT`, the new filing supersedes it — the prior draft's `status` becomes `SUPERSEDED`. A fresh assessment is itself `DRAFT` with `certified` false.

The assessment's `composite_score` is computed from the four factors with market harm counting double: `purpose` plus `nature` plus `amount` plus twice `market`, giving a range of 5 to 20. Certification rests with a `LegalCertifier` and three gates. The composite must meet the bar — a `composite_score` of at least 13, with anything lower rejected as `ERR_FAIR_USE_SCORE_LOW`. The certifier must not be the person who asked: the caller's `X-User-ID` is compared to the id of the requester who filed the assessment, and a match is `ERR_SEGREGATION_OF_DUTIES`. And the asset's posture must not be `RETIRED` — certification against a retired asset is rejected with `ERR_ASSET_POSTURE_BLOCKED` (HTTP 409). Certification sets `certified` true and moves the assessment `DRAFT` → `CERTIFIED`; the linked request simply stays in `FAIR_USE_ROUTE`. A `LegalCertifier` may instead reject a draft outright — `DRAFT` → `REJECTED`, no further conditions. `CERTIFIED`, `REJECTED`, and `SUPERSEDED` are all terminal.

### 3.9. Expiration Sweeps, Renewal Alerts, and Asset Retirement

The clock's sweeps close out what people forget. A license whose `term_end_at` the clock has reached moves `ACTIVE` → `EXPIRED`; its `HELD` reservations are forfeited, and its renewal alert — if still `SCHEDULED` — fires when its `fires_at` has been reached and is cancelled when it has not. Renewal alerts exist to warn the desk ahead of the end: created at grant in `SCHEDULED` with `fires_at` thirty days before `term_end_at`, an alert moves `SCHEDULED` → `FIRED` when the clock reaches `fires_at` while the license is still `ACTIVE`, and `SCHEDULED` → `CANCELLED` when the license is suspended, revoked, or expires before `fires_at`, or when the asset is retired. Alerts are listable per license and as a cross-license desk worklist, filterable by `status`.

Retirement is the asset's own ending, an `AssetCurator` action gated by three preconditions. The asset must not already be `RETIRED` — a second retirement is `ERR_ALREADY_TERMINAL`. No license on the asset may stand in `ACTIVE` or `SUSPENDED` lifecycle — live licenses block retirement with `ERR_ASSET_HAS_LIVE_LICENSES`. And no clearance request may still be open — a request in `SUBMITTED`, `HOLDER_REVIEW`, `NEGOTIATING`, or `APPROVED` blocks with `ERR_ASSET_HAS_OPEN_REQUESTS`. When retirement proceeds, `retired_at` is set to the current clock and is immutable thereafter, the posture becomes `RETIRED`, requests already in `DENIED`, `WITHDRAWN`, or `EXPIRED` are left untouched, and any renewal alert still `SCHEDULED` under any of the asset's licenses is `CANCELLED`.

## 4. Endpoint Definitions

All endpoints live under the `/rights` prefix. Creating a new resource returns HTTP 201 with the created resource in `data`; modifications, actions, and reads return HTTP 200. Request bodies, response shapes, guards, and side effects are as specified in §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /rights/_clock/set_current_utc | Set the logical clock and run all clock-driven sweeps | AssetCurator |
| POST | /rights/rights-holders | Register a rights holder | AssetCurator |
| GET | /rights/rights-holders/{id} | Get a rights holder | AssetCurator, ClearanceOfficer, Negotiator, Requester, LegalCertifier, FinancePayer, IngestionAgent |
| GET | /rights/rights-holders | List rights holders | AssetCurator, ClearanceOfficer, Negotiator, Requester, LegalCertifier, FinancePayer, IngestionAgent |
| POST | /rights/assets | Register an asset with rights metadata | AssetCurator |
| GET | /rights/assets/{id} | Get an asset, with computed posture | AssetCurator, ClearanceOfficer, Negotiator, Requester, LegalCertifier, FinancePayer, IngestionAgent |
| GET | /rights/assets | List assets, filterable | AssetCurator, ClearanceOfficer, Negotiator, Requester, LegalCertifier, FinancePayer, IngestionAgent |
| POST | /rights/assets/{id}/retire | Retire an asset | AssetCurator |
| POST | /rights/assets/{id}/diligence-logs | Append an orphan-work diligence record | AssetCurator |
| GET | /rights/assets/{id}/diligence-logs | List an asset's diligence records | AssetCurator, ClearanceOfficer, LegalCertifier |
| POST | /rights/assets/{id}/clearance-requests | Create a clearance request | Requester |
| GET | /rights/clearance-requests/{id} | Get a clearance request | AssetCurator, ClearanceOfficer, Negotiator, Requester, LegalCertifier, FinancePayer |
| GET | /rights/clearance-requests | Desk worklist of clearance requests, filterable | AssetCurator, ClearanceOfficer, Negotiator, Requester, LegalCertifier, FinancePayer |
| GET | /rights/assets/{id}/clearance-requests | List clearance requests for an asset | AssetCurator, ClearanceOfficer, Negotiator, Requester, LegalCertifier, FinancePayer |
| POST | /rights/clearance-requests/{id}/advance | Advance the request one step (OCC-guarded) | ClearanceOfficer |
| POST | /rights/clearance-requests/{id}/deny | Deny the request | ClearanceOfficer |
| POST | /rights/clearance-requests/{id}/withdraw | Requester withdraws their own request | Requester |
| POST | /rights/clearance-requests/{id}/grant | Grant a license from an approved request | ClearanceOfficer |
| POST | /rights/clearance-requests/{id}/rounds | Post a negotiation round, optionally accepting it | Negotiator, RightsHolderRep |
| GET | /rights/clearance-requests/{id}/rounds | List a request's negotiation rounds | ClearanceOfficer, Negotiator, RightsHolderRep, Requester, LegalCertifier, FinancePayer |
| GET | /rights/licenses/{id} | Get a license with computed usage fields | AssetCurator, ClearanceOfficer, Negotiator, LegalCertifier, FinancePayer, IngestionAgent |
| GET | /rights/licenses | List licenses, filterable | AssetCurator, ClearanceOfficer, Negotiator, LegalCertifier, FinancePayer, IngestionAgent |
| POST | /rights/licenses/{id}/revoke | Revoke a license backed by an upheld takedown | LegalCertifier |
| POST | /rights/licenses/{id}/usage-reservations | Reserve usage units (OCC-guarded) | IngestionAgent |
| GET | /rights/licenses/{id}/usage-reservations | List a license's reservations | ClearanceOfficer, IngestionAgent, FinancePayer |
| GET | /rights/usage-reservations/{id} | Get a usage reservation | ClearanceOfficer, IngestionAgent, FinancePayer |
| GET | /rights/usage-reservations/{id}/usage-events | List events that drew down a reservation | ClearanceOfficer, IngestionAgent, FinancePayer |
| POST | /rights/usage-reservations/{id}/release | Release a held reservation | IngestionAgent |
| POST | /rights/licenses/{id}/usage-events | Post actual usage, with or without a reservation | IngestionAgent |
| GET | /rights/licenses/{id}/usage-events | List a license's usage events | ClearanceOfficer, IngestionAgent, FinancePayer, LegalCertifier |
| POST | /rights/licenses/{id}/payments | Post a payment or refund (OCC-guarded) | FinancePayer |
| GET | /rights/licenses/{id}/payments | List a license's payments | ClearanceOfficer, FinancePayer, LegalCertifier |
| POST | /rights/assets/{id}/fair-use-assessments | File a fair-use assessment, rerouting the linked request | Requester |
| GET | /rights/fair-use-assessments/{id} | Get a fair-use assessment | AssetCurator, ClearanceOfficer, Requester, LegalCertifier |
| GET | /rights/assets/{id}/fair-use-assessments | List an asset's fair-use assessments | AssetCurator, ClearanceOfficer, Requester, LegalCertifier |
| GET | /rights/fair-use-assessments | List fair-use assessments across assets, filterable | AssetCurator, ClearanceOfficer, Requester, LegalCertifier |
| POST | /rights/fair-use-assessments/{id}/certify | Certify a fair-use assessment | LegalCertifier |
| POST | /rights/fair-use-assessments/{id}/reject | Reject a fair-use assessment | LegalCertifier |
| POST | /rights/assets/{id}/takedown-notices | File a DMCA takedown notice | AssetCurator |
| GET | /rights/assets/{id}/takedown-notices | List an asset's takedown notices | AssetCurator, ClearanceOfficer, LegalCertifier, FinancePayer |
| GET | /rights/takedown-notices/{id} | Get a takedown notice | AssetCurator, ClearanceOfficer, LegalCertifier, FinancePayer |
| POST | /rights/takedown-notices/{id}/counter | File a counter-notice before the window lapses | AssetCurator |
| POST | /rights/takedown-notices/{id}/retract | Retract a notice | AssetCurator |
| GET | /rights/licenses/{id}/renewal-alerts | List a license's renewal alerts | ClearanceOfficer, FinancePayer, AssetCurator |
| GET | /rights/renewal-alerts | Desk worklist of all renewal alerts, filterable | ClearanceOfficer, AssetCurator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_OWNER_ONLY | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_ASSET_POSTURE_BLOCKED | 409 |
| ERR_ASSET_HAS_LIVE_LICENSES | 409 |
| ERR_ASSET_HAS_OPEN_REQUESTS | 409 |
| ERR_MEDIA_NOT_PERMITTED | 409 |
| ERR_RIGHTS_HOLDER_UNIDENTIFIED | 409 |
| ERR_ORPHAN_DILIGENCE_INCOMPLETE | 409 |
| ERR_NEGOTIATION_EXHAUSTED | 409 |
| ERR_ROUND_ROLE_ALTERNATION | 409 |
| ERR_MFN_FLOOR_VIOLATION | 422 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_FEE_MISMATCH | 422 |
| ERR_LICENSE_WINDOW_OVERLAP | 422 |
| ERR_LICENSE_ALREADY_EXISTS | 409 |
| ERR_INVALID_WINDOW | 422 |
| ERR_EMBARGO_ACTIVE | 422 |
| ERR_USAGE_OUTSIDE_TERM | 422 |
| ERR_LICENSE_NOT_ACTIVE | 409 |
| ERR_HOLD_EXPIRED | 409 |
| ERR_USAGE_OVERDRAW | 409 |
| ERR_QUOTA_EXCEEDED | 409 |
| ERR_COUNTER_WINDOW_LAPSED | 409 |
| ERR_NO_UPHELD_TAKEDOWN | 409 |
| ERR_LICENSE_NOT_PAYABLE | 422 |
| ERR_OVERPAYMENT | 422 |
| ERR_REFUND_REQUIRES_TERMINAL | 422 |
| ERR_REFUND_AFTER_USE | 422 |
| ERR_FAIR_USE_MEDIA_INELIGIBLE | 409 |
| ERR_FAIR_USE_SCORE_LOW | 422 |
