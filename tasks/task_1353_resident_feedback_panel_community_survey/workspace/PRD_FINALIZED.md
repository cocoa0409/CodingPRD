# Resident Feedback Panel API — Product Requirements Document

## 1. Introduction

Municipal decisions are only as defensible as the resident evidence behind them, and ad-hoc outreach routinely over-represents the households that are easiest to reach. The Resident Feedback Panel API runs a standing, demographically quota-managed survey panel for a city: residents are recruited into explicit demographic cells defined by age band, district, and housing tenure; survey instruments are authored, translated, and certified before any wave goes into the field; invitations are dispatched under strict contact-discipline rules; responses are reviewed and compensated through a segregated incentive pipeline; and results are weighted, de-identified, and published with per-department follow-up commitments tracked to fulfillment or breach.

This document specifies the API's global contracts — authentication, response envelopes, pagination, derived counters, optimistic concurrency, and validation ordering — and then its business workflows: quota-frame management, the panelist membership lifecycle, instrument and translation certification, wave fielding and close, invitation discipline, response review and incentive administration, weighting and publication, department commitments, privacy holds, and panel refresh. All panel resources are served under the `/feedback-panel` mount; a single administrative clock capability lives outside that mount. Consistency is immediate: every mutation and every cascade it triggers commits atomically within the request that caused it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. The recognized roles are exactly six: `PanelManager`, `SurveyDesigner`, `DataAnalyst`, `IncentiveClerk`, `PrivacyOfficer`, and `DepartmentLiaison`. A request missing either header, or naming a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All six roles use opaque operator identities. When `X-User-Role` is `PanelManager`, `SurveyDesigner`, `DataAnalyst`, `IncentiveClerk`, or `PrivacyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `finalized_by_user_id` on a weight snapshot when a `DataAnalyst` finalizes it — but never compares it to any entity's `id`. When `X-User-Role` is `DepartmentLiaison`, `X-User-ID` carries the department name itself: it remains opaque with respect to entity ids, but department-scoped commitment actions compare it for exact string equality against the commitment's `department_name`, and a mismatch is rejected with `ERR_FORBIDDEN_DEPARTMENT` (HTTP 403).

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Version Semantics

Every resource in the panel program — demographic cells, panelists, instruments, translations, waves, invitations, responses, incentive awards, weight snapshots, publications, follow-up commitments, privacy holds, and refresh runs — carries a common metadata spine:

- `id` (string): a server-minted UUID, formatted without any type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every mutation to the resource, used for optimistic concurrency control.

The spine's timestamp format applies everywhere: every other non-null timestamp the API serves — a wave's `opens_at` and `closes_at`, an invitation's `sent_at` and `last_reminder_at`, a panelist's `last_contacted_at` and `lapsed_at`, a commitment's `due_at` and `breached_at`, and the clock endpoint's `current_utc` — is likewise serialized as an ISO 8601 UTC timestamp with three fractional digits.

Mutation is defined broadly. System-driven reconciliations count: when a derived counter on a cell or wave moves — a reservation changing a cell's `reserved_count`, funds moving between a wave's incentive buckets, a streak-driven lapse changing seated counts — the owning resource's `updated_at` refreshes and its `version` increments exactly as if a client had edited it. One field is deliberately exempt from post-creation change: an incentive award's `amount_cents` is computed once when the award is minted and is fixed thereafter.

### 2.5. The Logical Clock

All temporal reasoning in the system — fielding windows, contact washouts, reminder cadence, commitment deadlines, attrition grace periods, and the chronological ordering a streak walk depends on — reads a single logical clock, never the host's wall clock. At startup, before any administrative intervention, the clock reads exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time.

The clock advances only through an administrative capability restricted to `PanelManager`, exposed outside the panel namespace at `/_clock/set_current_utc`. A call supplies a `to_iso8601` instant, advances the logical clock to it, and returns the resulting `current_utc`. Every rule in this document phrased as "now" or "the current time" refers to this clock.

### 2.6. Quota Ledgers and Derived Counters

The program maintains two families of always-current derived counters, reconciled immediately inside whichever request perturbs them — never by a background job.

On each demographic cell, `reserved_count` is the number of live invitations — those in `SENT` status — whose panelist is seated in that cell, and `active_count` is the number of seated panelists whose membership status is `ACTIVE`, `LAPSED`, or `SUSPENDED`; applicants and panelists who have attrited or withdrawn never count. A cell's `status` is never set by clients: it is `OPEN` while `active_count` is below `target_size` and `SATURATED` once `active_count` reaches or exceeds `target_size`, re-derived automatically on every count change and every target change, with each re-derivation that mutates the cell incrementing its `version`.

On each survey wave, `incentive_pool_available_cents` is the uncommitted remainder of the incentive pool, `incentive_pool_reserved_cents` is the sum of award amounts whose payout is currently authorized, `incentive_pool_paid_cents` is the sum already paid out, `invited_count` counts invitations ever dispatched for the wave, and `completed_count` counts the wave's invitations that have reached `COMPLETED`. These buckets move only through the workflows of §3: dispatch, completion, expiry, decline, suppression, award authorization, payment, and forfeiture.

### 2.7. Optimistic Concurrency Control

Two write operations guard their parent resource with optimistic concurrency, and both require the version field as a non-optional input:

- Creating a weight snapshot against a wave — `POST /feedback-panel/survey-waves/{id}/weight-snapshots` — requires the request to carry `expected_wave_version` equal to that wave's current `version`. If the wave's version has advanced since the client last observed it — because a prior snapshot was created or finalized, or a pool mutation occurred — the create is rejected with `ERR_STALE_WAVE_VERSION` (HTTP 412) rather than silently superseding state the client never saw.
- Adjusting a demographic cell's recruitment target — `POST /feedback-panel/panel-cells/{id}/targets` — requires `expected_cell_version` equal to that cell's current `version`; a mismatch is rejected with `ERR_STALE_CELL_VERSION` (HTTP 412) rather than clobbering newer quota state.

Endpoints not listed here do not take a version field.

### 2.8. Validation Order and Error Precedence

When several rules could reject the same request, the server evaluates them in a fixed priority order and surfaces the earliest failure:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is declared — otherwise `ERR_UNAUTHENTICATED` (HTTP 401). This applies to all endpoints.
2. **Authorization.** The caller's role is listed on the endpoint — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). Department-scoped commitment actions additionally require the caller's `X-User-ID` to equal the commitment's `department_name`, failing as `ERR_FORBIDDEN_DEPARTMENT` (HTTP 403).
3. **Existence.** Path identifiers are validated left to right along the URL, so a missing parent is reported before a missing child, and every foreign-key reference in the request body must resolve. Failures surface as the resource-specific not-found errors: `ERR_PANEL_CELL_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`, `ERR_TRANSLATION_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_INVITATION_NOT_FOUND`, `ERR_RESPONSE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, `ERR_PUBLICATION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_PRIVACY_HOLD_NOT_FOUND`, and `ERR_REFRESH_RUN_NOT_FOUND` (all HTTP 404).
4. **Request shape.** Missing required fields, wrong types, enum values outside their declared sets, and range violations — `completeness_pct` must lie between 0 and 100 inclusive, `min_response_rate` must be greater than 0 and at most 1, `closes_at` must be strictly later than `opens_at`, `question_count` must be at least 1, `target_size` must be at least 0 — all fail as `ERR_INVALID_REQUEST` (HTTP 400). Duplicates of unique fields (a repeated `wave_code`, a repeated `external_ref`, or a demographic triple already claimed by another cell) and a publication create whose `weight_snapshot_id` does not belong to its `wave_id` also fail as `ERR_INVALID_REQUEST`.
5. **Stale-version OCC.** On the two guarded writes of §2.7, `expected_wave_version` or `expected_cell_version` must equal the parent's current `version` — otherwise `ERR_STALE_WAVE_VERSION` or `ERR_STALE_CELL_VERSION` (HTTP 412).
6. **State preconditions.** The target resource must be in the from-state the operation requires: the wave `FIELDING` for dispatch and reminders, `ARMED` for opening fielding; the instrument `LOCKED` for arming, `IN_REVIEW` or `APPROVED` for certification; the panelist `LAPSED` for reactivation; the snapshot the wave's latest for finalization; the publication `DRAFT` for publishing; and every award, response, invitation, commitment, hold, and refresh run in the state its transition requires. Violations surface the state-specific 409 errors catalogued in §5, and terminal states reject all further transitions.
7. **Privacy and duty segregation.** An `ACTIVE` privacy hold on the panelist bars invitation dispatch and panelist reactivation (`ERR_PRIVACY_HOLD_ACTIVE`, HTTP 403), and the operator publishing a publication must not be the one who finalized its pinned snapshot (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403).
8. **Temporal rules.** The fielding window (`ERR_WAVE_WINDOW_NOT_OPEN`), the seven-day contact washout (`ERR_CONTACT_WASHOUT_VIOLATION`), the 48-hour reminder cadence (`ERR_REMINDER_CADENCE_TOO_SOON`), and the commitment deadline rules (`ERR_COMMITMENT_OVERDUE`, `ERR_COMMITMENT_NOT_OVERDUE`) — all HTTP 409.
9. **Uniqueness and capacity.** Evaluated within this priority in exactly the following order: a duplicate live invitation for the same wave and panelist (`ERR_DUPLICATE_INVITATION`); cell saturation at seating time (`ERR_CELL_SATURATED`); the per-cell contact cap (`ERR_CELL_CONTACT_CAP_REACHED`); one active hold per panelist (`ERR_PRIVACY_HOLD_EXISTS`); one non-rejected translation per instrument and locale (`ERR_DUPLICATE_TRANSLATION`); the k-anonymity gate (`ERR_K_ANONYMITY_VIOLATION`, HTTP 422); snapshot computability (`ERR_WEIGHTS_NOT_COMPUTABLE`, HTTP 422); and the early-close response-rate gate (`ERR_MIN_RESPONSE_NOT_MET`).
10. **Fiscal sufficiency.** Dispatch requires the wave's available pool to cover the base incentive, and award authorization requires it to cover the award amount — otherwise `ERR_INCENTIVE_POOL_INSUFFICIENT` (HTTP 402).

### 2.9. Privacy, De-identification, and Segregation of Duties

Panelist identity is handled as regulated data throughout. A panelist's `external_ref` is a registrar-supplied contact reference token and `full_name` is direct PII; both carry restricted visibility. A response's `answers_payload` is PII-adjacent and is visible to the `DataAnalyst` reviewing it, but never to the `IncentiveClerk`, who sees award amounts and statuses only.

Publication is de-identified by construction. Breakdowns are reported per demographic cell, never per person; any represented cell whose respondent count falls below the publication's `k_threshold` is flagged as suppressed in the breakdown, and publishing is refused outright while any represented cell has at least one but fewer than `k_threshold` respondents.

Duties are deliberately split across roles so that no single operator can both shape results and release them. Response review, weighting, analysis, and publication drafting belong to the `DataAnalyst`; incentive authorization, payment, and forfeiture belong to the `IncentiveClerk`; privacy holds, the de-identification gate, and publish/retract belong to the `PrivacyOfficer`. The sharpest edge of this split is enforced at publish time: the publisher must be a different operator than the snapshot's finalizer.

### 2.10. Numeric Precision and Rounding

Analytic quantities — the representativeness score, response weights, `weight_mass`, per-cell weighted shares, the design effect, and projected and final response rates — are reported to exactly 6 decimal places with round-half-up rounding.

Money is integer cents. Award computation rounds half-up at each pinned step rather than once at the end, and pool buckets are exact integer sums. Counts — streaks, respondents, reminders, invitations — are integers, and contact-discipline windows compare timestamps at second resolution.

## 3. Business Logic & Workflows

### 3.1. The Demographic Quota Frame

Representativeness is engineered before the first resident is contacted. A `PanelManager` defines the frame by creating demographic cells, each identified by an `age_band` (one of `AGE_18_29`, `AGE_30_44`, `AGE_45_64`, or `AGE_65_PLUS`), a `district` code such as D1 through D9, and a `tenure_bucket` of `RENTER` or `OWNER`. The demographic triple is unique across the program — a create repeating an existing triple fails as `ERR_INVALID_REQUEST` — and each cell carries a `target_size`, the desired number of seated panelists, which must be at least 0. A new cell starts with `reserved_count` 0 and `active_count` 0; its `status` follows the derivation rule of §2.6, so a cell created with `target_size` 0 begins `SATURATED` and any other new cell begins `OPEN`. The cell list read supports an optional `status` filter.

Targets move as the program learns. Adjusting a cell's target takes a new `target_size` and re-derives saturation against the population already seated, incrementing the cell's `version` by one. Because intervening enrollments, attritions, and withdrawals also advance that version, the adjust call must carry `expected_cell_version` under the OCC rule of §2.7 and fails with `ERR_STALE_CELL_VERSION` when the client's last observed version no longer matches.

Every cell's shortfall is its deficit: `target_size` minus `active_count`, never below zero, where only panelists in `ACTIVE`, `LAPSED`, or `SUSPENDED` count as seated and `APPLICANT`, `ATTRITED`, and `WITHDRAWN` panelists are excluded. From these deficits the program computes a representativeness score across all cells regardless of wave. Let T be the sum of `target_size` over every cell; cells with `target_size` 0 contribute nothing to T or to the score, and if T is 0 the score is 100. Otherwise each cell with a positive target contributes its deficit divided by its `target_size` — the ratio capped at 1.0 — weighted by that cell's share of T, and the score is 100 minus 100 times the sum of those weighted ratios, reported to six decimal places with round-half-up rounding. A program seated exactly to target everywhere scores 100. The score is surfaced on the wave analysis read described in §3.7.

### 3.2. Panelist Recruitment, Seating, and Membership Lifecycle

A `PanelManager` registers each applicant with the registrar's `external_ref` (unique across the panel; a repeat fails as `ERR_INVALID_REQUEST`), the `full_name`, the declared `age_band`, `district`, and `tenure_bucket`, and an optional `preferred_locale` that defaults to `en` and later drives both translation coverage and a locale bonus on incentives. New registrations enter as `APPLICANT` with `missed_streak` 0 and `last_contacted_at` null, since the system has never contacted them. Panelist list reads accept optional `status` and `home_cell_id` filters.

Seating an applicant is the enrollment action. The system first locates the cell matching the applicant's declared triple exactly; when no such cell exists, enrollment fails with `ERR_PANEL_CELL_NOT_FOUND`. When the matching cell's `active_count` has already reached its `target_size`, enrollment fails with `ERR_CELL_SATURATED`. Otherwise the panelist's `home_cell_id` is resolved to that cell, the panelist moves `APPLICANT` → `ACTIVE`, the cell's `active_count` increases by one, its status re-derives, and its `version` increments.

Membership then follows a six-state lifecycle — `APPLICANT`, `ACTIVE`, `LAPSED`, `SUSPENDED`, `ATTRITED`, `WITHDRAWN` — with `ATTRITED` and `WITHDRAWN` terminal. A `PanelManager` may withdraw a panelist from either `ACTIVE` or `LAPSED`. Both withdrawals decrement the home cell's `active_count`, re-derive its status, and increment its `version`; withdrawing from `ACTIVE` additionally moves the panelist's live `SENT` invitations to `SUPPRESSED`, with each affected cell's `reserved_count` re-derived.

Lapse is earned, not assigned. Each panelist's `missed_streak` counts consecutive expirations at the front of their contact history: the panelist's invitations across all waves are ordered by their wave's `closes_at`, most recent first, with ties broken by the invitation's own `created_at`, most recent first; walking from the front, the system counts leading invitations in `EXPIRED` status and stops at the first `COMPLETED` or `DECLINED`. `SUPPRESSED` invitations are skipped entirely — streak-neutral, neither extending nor breaking the count. When a wave close sweep recomputes a panelist's streak at 2 or more, the panelist transitions `ACTIVE` → `LAPSED`, `lapsed_at` is stamped with the current time, and the streak resets to 0, consumed by the lapse.

A lapsed panelist can return. Reactivation requires the panelist to currently be `LAPSED` — anything else fails with `ERR_PANELIST_NOT_LAPSED` — and requires that no `ACTIVE` privacy hold exists for them, else `ERR_PRIVACY_HOLD_ACTIVE`. Because `LAPSED` already counts toward `active_count`, reactivation leaves the count unchanged in kind and simply re-derives the cell's status as the panelist returns to `ACTIVE`.

### 3.3. Instrument Authoring and Translation Certification

A `SurveyDesigner` authors an instrument with a `title`, a `question_count` of at least 1, the set of `required_locales` that must hold certified translations before approval, and an optional `base_locale` defaulting to `en`; the `base_locale` must itself appear in `required_locales`, and a `question_count` below 1 fails as `ERR_INVALID_REQUEST`. New instruments are `DRAFT` at `revision` 1. The instrument list read supports a `status` filter.

The instrument lifecycle runs `DRAFT` → `IN_REVIEW` → `APPROVED` → `LOCKED` with a deliberate revision loop. Submitting for review moves `DRAFT` → `IN_REVIEW`. Approval moves `IN_REVIEW` → `APPROVED` and requires that every locale in `required_locales` holds a translation in `CERTIFIED` status certifying the instrument's current `revision`; if any required locale lacks one, approval fails with `ERR_TRANSLATION_NOT_CERTIFIED`. Revision loops back to `DRAFT`: from `IN_REVIEW` the `revision` is unchanged, while from `APPROVED` the `revision` increments by one and every `CERTIFIED` translation whose `instrument_revision` now trails the instrument's `revision` flips to `STALE`. Locking moves `APPROVED` → `LOCKED`; a locked instrument is immutable and waves may arm against it. Any instrument transition that is not valid from its current status — including everything attempted from `LOCKED` — is rejected with `ERR_INSTRUMENT_INVALID_STATE`.

Translations carry their own lifecycle under the same role. Creating one takes the `instrument_id`, the `locale`, and a `translator_ref`; it enters `SUBMITTED` with `instrument_revision` copied from the instrument's current `revision`. At most one non-`REJECTED` translation may exist per instrument and locale — a second live one fails with `ERR_DUPLICATE_TRANSLATION` — and translation list reads accept `instrument_id`, `locale`, and `status` filters. Certification moves `SUBMITTED` → `CERTIFIED` and is guarded by two checks in this order: the instrument must be `IN_REVIEW` or `APPROVED` (otherwise `ERR_INSTRUMENT_NOT_IN_REVIEW`), and the translation's `instrument_revision` must equal the instrument's current `revision` (otherwise `ERR_TRANSLATION_STALE_REVISION`). Rejection moves `SUBMITTED` → `REJECTED`. Resubmission moves `REJECTED` or `STALE` back to `SUBMITTED` and re-pins `instrument_revision` to the instrument's current `revision`. Any other translation transition is rejected with `ERR_TRANSLATION_INVALID_STATE`.

### 3.4. Survey Wave Preparation, Fielding, and Close

A wave is the unit of fielding. A `PanelManager` creates one with a unique `wave_code`, the `instrument_id` it will field, an inclusive `opens_at` and `closes_at` window with `closes_at` strictly later than `opens_at`, a `min_response_rate` greater than 0 and at most 1, and the incentive economics — `incentive_pool_total_cents` and `base_incentive_cents`, each at least 0. A new wave is `DRAFT`; its pool begins entirely uncommitted, with `incentive_pool_available_cents` equal to the total and `incentive_pool_reserved_cents` and `incentive_pool_paid_cents` at 0, and `invited_count` and `completed_count` start at 0. Wave list reads filter by `instrument_id` or `status`.

Arming readies a wave and is guarded by three checks: the instrument must be `LOCKED` (else `ERR_INSTRUMENT_NOT_LOCKED`); every locale in its `required_locales` must hold a `CERTIFIED` translation at the instrument's current `revision` (else `ERR_TRANSLATION_NOT_CERTIFIED`); and the current time must not yet be past `opens_at` (else `ERR_WAVE_WINDOW_NOT_OPEN`). Opening fielding moves `ARMED` → `FIELDING` and requires the current time to fall within the declared window inclusive of both bounds — outside it, `ERR_WAVE_WINDOW_NOT_OPEN` — and attempting it from any status other than `ARMED` is `ERR_WAVE_NOT_ARMED`. A wave may be cancelled from `DRAFT` or `ARMED`, landing in `CANCELLED`. Other wave moves are invalid: arming an already-`ARMED` wave or cancelling a `FIELDING` one is rejected with `ERR_WAVE_INVALID_STATE`, and `PUBLISHED` and `CANCELLED` are terminal — any further transition attempt against them fails with `ERR_WAVE_ALREADY_TERMINAL`.

Closing ends fielding. The wave must be `FIELDING`; closing from any other non-terminal status fails with `ERR_WAVE_NOT_FIELDING`. One of two gates must then hold: either the current time is strictly past `closes_at`, or the wave closes early with at least one invitation dispatched and the ratio of `completed_count` to `invited_count` at least `min_response_rate`; failing both yields `ERR_MIN_RESPONSE_NOT_MET`. A successful close cascades in three hops. First, every invitation of the wave still `SENT` moves to `EXPIRED`. Second, for each affected panelist the `missed_streak` is recomputed by the chronological walk of §3.2 — each expiry extends its owner's streak — and each expiry releases its reservation, so the home cells' `reserved_count` re-derives. Third, panelists whose recomputed streak reaches 2 lapse: `ACTIVE` → `LAPSED`, with `lapsed_at` stamped and the streak reset to 0.

After close, two system transitions finish the wave's arc. Finalizing a weight snapshot moves the wave `CLOSED` → `WEIGHTED`, and publishing a publication moves it `WEIGHTED` → `PUBLISHED`. Creating a new snapshot for a `WEIGHTED` wave reopens analysis by reverting it `WEIGHTED` → `CLOSED`.

### 3.5. Invitation Dispatch, Reminders, and Contact Discipline

Dispatch is the most heavily guarded write in the system. A `PanelManager` dispatches an invitation with a payload naming the `wave_id` and `panelist_id`, and the request is evaluated along the §2.8 ladder: the wave must be `FIELDING` (otherwise `ERR_WAVE_NOT_FIELDING`) and the panelist must be `ACTIVE` (otherwise `ERR_PANELIST_NOT_ACTIVE`); no `ACTIVE` privacy hold may exist for the panelist (otherwise `ERR_PRIVACY_HOLD_ACTIVE`); the contact washout must be satisfied; the uniqueness and capacity checks run in their pinned order; and the fiscal floor is checked last.

The washout is a per-panelist buffer. When `last_contacted_at` is set, dispatch earlier than seven days after it is rejected with `ERR_CONTACT_WASHOUT_VIOLATION`, while dispatch at exactly the seven-day mark is permitted — the buffer is half-open. Capacity then runs in its pinned intra-priority order: a live `SENT` invitation already existing for the same wave and panelist pair is rejected with `ERR_DUPLICATE_INVITATION`, and the per-cell contact cap is rejected with `ERR_CELL_CONTACT_CAP_REACHED` when the count of invitations sent into the panelist's home cell — of any status, since contact occurred — within the trailing seven-day window inclusive of both endpoints has reached 3. Finally, dispatch requires the wave's `incentive_pool_available_cents` to cover at least `base_incentive_cents`, else `ERR_INCENTIVE_POOL_INSUFFICIENT`.

A successful dispatch creates the invitation directly in `SENT`. Both `sent_at` and the panelist's `last_contacted_at` are stamped with the current time; the cell's `reserved_count` increases by one with its `version` incrementing; and the wave's `invited_count` increases by one with its `version` incrementing. Invitations carry a `reminder_count` starting at 0 and a `last_reminder_at` that stays null until the first reminder, and invitation list reads filter by `wave_id`, `panelist_id`, or `status`.

Reminders are a self-transition on `SENT`. A reminder is refused when the wave is no longer `FIELDING` (`ERR_WAVE_NOT_FIELDING`), when `reminder_count` has already reached 2 (`ERR_REMINDER_CAP_REACHED`), or when fewer than 48 hours have elapsed since the most recent reminder — or since `sent_at` when none has been sent; a reminder at exactly the 48-hour mark is permitted, and anything sooner is rejected with `ERR_REMINDER_CADENCE_TOO_SOON`. Each successful reminder increments `reminder_count` and stamps `last_reminder_at` with the current time.

Two outcomes close an invitation out from the panel side. A `PanelManager` may record a decline, moving `SENT` → `DECLINED`, which releases the cell reservation — `reserved_count` decreases by one — and recomputes the streak, since a decline breaks it. Submitting a response moves the invitation `SENT` → `COMPLETED`, increases the wave's `completed_count` by one, likewise releases the reservation, and recomputes the streak, since a completion also breaks it. Either action against an invitation no longer `SENT` fails with `ERR_INVITATION_NOT_OPEN`, and so does a response submitted against one. Two further terminal outcomes are system-driven: expiry during the wave close cascade (`SENT` → `EXPIRED`, which extends the streak), and suppression (`SENT` → `SUPPRESSED`, streak-neutral) when a full-suppression hold lands or the panelist withdraws.

### 3.6. Response Intake, Review, and Incentive Administration

A `PanelManager` submits a response on the respondent's behalf with the `invitation_id`, the `answers_payload` map, a `completeness_pct` between 0 and 100 inclusive, and `completion_seconds` of at least 0. There is at most one response per invitation: a second submission finds the invitation already `COMPLETED` and fails with `ERR_INVITATION_NOT_OPEN`. On creation the response is `SUBMITTED`; its `wave_id` and `panelist_id` are copied from the invitation; and two quality flags are computed — `speeder_flag` is true when `completion_seconds` is under 120, and `low_effort_flag` is true when `completeness_pct` is under 50, meaning fewer than half of the questions were answered. Exactly one incentive award is minted with the response, pinned to it via `response_id` with `wave_id` copied across for pool accounting, starting at `eligibility_status` `PENDING` and `payout_status` `UNPAID`. Response list reads filter by `invitation_id`, `wave_id`, `panelist_id`, or `status`.

The award's `amount_cents` is computed at minting time and never changes afterward, in a pinned evaluation order with per-component rounding. First, the completion bonus is the wave's `base_incentive_cents` multiplied by `completeness_pct` and divided by 100, rounded half-up to whole cents. Second, a locale bonus of ten percent of `base_incentive_cents`, likewise rounded half-up, applies when the panelist's `preferred_locale` is anything other than `en`; an English-locale panelist receives zero here. Third, the subtotal is the base plus the completion bonus plus the locale bonus. Fourth, when `speeder_flag` is set the subtotal is halved with round-half-up rounding. Fifth, the amount is the subtotal capped at 10,000 cents — one hundred dollars per response at most. The order is load-bearing: rounding each component before summing yields different cents than summing the unrounded components whenever the completion or locale bonus lands on a half-cent boundary, and the pinned per-component order wins.

Review belongs to the `DataAnalyst`. Accepting moves a response `SUBMITTED` → `ACCEPTED` or `QUARANTINED` → `ACCEPTED` and flips its award's eligibility `PENDING` → `ELIGIBLE`. Quarantining moves `SUBMITTED` → `QUARANTINED` with no award effect. Discarding moves `QUARANTINED` → `DISCARDED` and flips eligibility `PENDING` → `INELIGIBLE`. `ACCEPTED` and `DISCARDED` are terminal, and any review action from a status that does not permit it — discarding a `SUBMITTED` response, accepting a discarded one, or touching a terminal response — is rejected with `ERR_RESPONSE_NOT_REVIEWABLE`.

Payment is the `IncentiveClerk`'s domain, a deliberately separate pair of hands. Authorization requires the award's `eligibility_status` to be `ELIGIBLE` and its `payout_status` to be `UNPAID` — otherwise `ERR_AWARD_NOT_AUTHORIZED_STATE` — and requires the wave's available pool to cover `amount_cents`, else `ERR_INCENTIVE_POOL_INSUFFICIENT`; on success the amount moves from `incentive_pool_available_cents` into `incentive_pool_reserved_cents` and the wave's `version` increments. Paying requires `payout_status` `AUTHORIZED` (else `ERR_AWARD_NOT_PAID_STATE`) and moves the amount from reserved into `incentive_pool_paid_cents`, again incrementing the wave's `version`. Forfeiting also requires `AUTHORIZED` (else `ERR_AWARD_NOT_FORFEIT_STATE`) and returns the amount from reserved back to available. Forfeiture additionally fires without clerk action: when a panelist attrits during a refresh apply, every `AUTHORIZED` award of theirs is forfeited by the system with the same pool movement. Once eligibility reaches `INELIGIBLE`, or payout reaches `PAID` or `FORFEITED`, that dimension of the award is closed. Award list reads filter by `response_id`, `wave_id`, `payout_status`, or `eligibility_status`.

### 3.7. Weighting, Analysis, and Publication

Once a wave is `CLOSED`, a `DataAnalyst` takes a weight snapshot against it, naming the `method` — `RIM` or `POST_STRAT` — and carrying `expected_wave_version` per §2.7; a stale value fails with `ERR_STALE_WAVE_VERSION` before any other evaluation. Creation is permitted only against a `CLOSED` or `WEIGHTED` wave: against any other non-terminal status it fails with `ERR_WAVE_INVALID_STATE`, and against a terminal wave with `ERR_WAVE_ALREADY_TERMINAL`. Creating the snapshot increments the wave's `version` by one, supersedes history — every prior `PROVISIONAL` or `FINALIZED` snapshot of the wave becomes `SUPERSEDED` — and, when the wave was `WEIGHTED`, reverts it `WEIGHTED` → `CLOSED` as analysis reopens. The new snapshot begins `PROVISIONAL`, with its `wave_id` taken from the create path. Snapshot list reads filter by `wave_id` or `status`.

The weights are computed over the wave's `ACCEPTED` responses only, grouped by each respondent's `home_cell_id`; `SUBMITTED`, `QUARANTINED`, and `DISCARDED` responses never enter the computation. Let N be the number of included responses: when N is 0, creation is refused with `ERR_WEIGHTS_NOT_COMPUTABLE`, and cells with no accepted responses are simply absent from the per-cell shares. Under `POST_STRAT`, each represented cell's raw weight is its `target_size` divided by the number of the wave's accepted responses seated in it, and every respondent in a cell receives that cell's raw weight. Under `RIM`, every respondent starts at weight 1 and a single deterministic rake pass runs over a fixed margin order: first the age-band margin, where each band's target is the sum of `target_size` across its cells and each band's current total is the sum of the weights of respondents seated in that band, scaling every such respondent's weight by the band's target divided by its current total; then the tenure margin, computed the same way over `RENTER` and `OWNER` after the age adjustment. Because both margins are attributes of whole cells, respondents sharing a cell still share a weight under raking; the two methods nevertheless diverge whenever cells share a margin.

Both variants then run the same pinned tail. First the raw weights are normalized so they sum to N, multiplying each weight by N divided by their current sum. Then each weight is trimmed at five times the mean weight — the mean being exactly 1 after normalization, the cap is 5. Finally the weights are renormalized exactly once, again multiplying each by N divided by their current sum. The snapshot's `weight_mass` is the sum of the final weights, equal to N up to rounding; `accepted_count` records N; `weighted_cell_shares` maps each represented cell to the sum of its respondents' weights divided by `weight_mass`; and `design_effect` is one plus the square of the ratio of the standard deviation of the included weights to their mean. Every reported value is rounded to six decimal places, round-half-up.

The wave analysis read, restricted to `DataAnalyst`, reports three numbers: `projected_response_rate`, `final_response_rate`, and `representativeness_score`. While the wave is `FIELDING`, the projection credits expected uptake on still-open invitations: `completed_count` plus half of the invitations still `SENT`, divided by `invited_count`. Once the wave is `CLOSED`, `WEIGHTED`, or `PUBLISHED`, the projection equals the final ratio of `completed_count` to `invited_count`. When no invitations were ever dispatched, the rate is 0. The `final_response_rate` is that completions-over-invitations ratio once the wave has closed and null before then, and the `representativeness_score` is the program-wide figure of §3.1.

Finalization commits a snapshot. The wave must be `CLOSED` (else `ERR_WAVE_NOT_CLOSED`), and the snapshot must be the wave's latest — one already `SUPERSEDED` fails with `ERR_SNAPSHOT_SUPERSEDED`. On success the snapshot moves `PROVISIONAL` → `FINALIZED`, `finalized_by_user_id` records the caller's `X-User-ID`, and the wave moves `CLOSED` → `WEIGHTED`.

Publication starts as a `DataAnalyst` draft pinning the analysis. The create carries `wave_id`, `weight_snapshot_id`, and `title`, with an optional `k_threshold` defaulting to 5; the pinned snapshot must belong to the named wave, or the create fails as `ERR_INVALID_REQUEST`. At creation the publication computes `breakdown_cells`: the wave's `ACCEPTED` responses are grouped by home cell, and each entry records the `cell_id`, the `n_respondents` count, the `weighted_share` mirroring the pinned snapshot's per-cell share, and a `suppressed` flag that is true when the cell has at least one but fewer than `k_threshold` respondents. Publication list reads filter by `wave_id`, `weight_snapshot_id`, or `status`.

Publishing is the `PrivacyOfficer`'s call and enforces four checks in this order: first, the pinned snapshot must be `FINALIZED` (`ERR_SNAPSHOT_NOT_FINALIZED`); second, the wave must be `WEIGHTED` (`ERR_WAVE_NOT_WEIGHTED`); third, the publisher's `X-User-ID` must differ from the snapshot's `finalized_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); and fourth, the k-anonymity gate — no breakdown cell may have at least one but fewer than `k_threshold` respondents, while a cell with exactly `k_threshold` respondents passes and cells with zero respondents are absent rather than violations (`ERR_K_ANONYMITY_VIOLATION`). A successful publish moves the publication `DRAFT` → `PUBLISHED` and the wave `WEIGHTED` → `PUBLISHED`. Retraction moves `PUBLISHED` → `RETRACTED` and cascades conditionally: the publication's commitments in `COMMITTED` or `IN_PROGRESS` move to `SUSPENDED`, while `FULFILLED` and `BREACHED` commitments are left unchanged.

### 3.8. Department Follow-Up Commitments

A publication is a promise to act, and commitments make departments answer for it. A `DepartmentLiaison` creates one against a `PUBLISHED` publication — any other publication status fails with `ERR_PUBLICATION_NOT_PUBLISHED` — supplying the `publication_id`, the `department_name`, a `summary` of the promised work, and a `due_at` deadline. The commitment begins `COMMITTED` with `breached_at` null. Commitment list reads filter by `publication_id`, `department_name`, or `status`.

Department scoping is strict: starting, fulfilling, and renegotiating a commitment each require the caller's `X-User-ID` to equal the commitment's `department_name` exactly, otherwise `ERR_FORBIDDEN_DEPARTMENT`. Starting moves `COMMITTED` → `IN_PROGRESS`. Fulfilling moves `IN_PROGRESS` → `FULFILLED` and is on time only when the current time is at or before `due_at`; a late fulfill is rejected with `ERR_COMMITMENT_OVERDUE`. Breach marking is the `PanelManager`'s escalation: from `COMMITTED` or `IN_PROGRESS`, when the current time is strictly past `due_at`, the commitment moves to `BREACHED` and `breached_at` is stamped with the current time; marking a commitment not yet overdue fails with `ERR_COMMITMENT_NOT_OVERDUE`. Renegotiation moves `BREACHED` → `COMMITTED` with a `new_due_at` that must lie strictly in the future — one at or before the current time fails with `ERR_COMMITMENT_OVERDUE` — and on success `due_at` becomes `new_due_at` and `breached_at` clears to null. Any commitment action from a status that does not permit it is rejected with `ERR_COMMITMENT_NOT_OPEN`, and `FULFILLED` and `SUSPENDED` are terminal.

### 3.9. Privacy Holds and Panel Refresh

Privacy intervention is immediate and scoped. A `PrivacyOfficer` places a hold with the `panelist_id`, a `scope`, and an audit `reason`; at most one `ACTIVE` hold may exist per panelist, and a second attempt fails with `ERR_PRIVACY_HOLD_EXISTS`. A `NO_CONTACT` hold bars invitation dispatch only. A `FULL_SUPPRESS` hold additionally suspends the panelist — `ACTIVE` → `SUSPENDED` — and moves their live `SENT` invitations to `SUPPRESSED`, with the affected cells' `reserved_count` re-derived. Hold list reads filter by `panelist_id` or `status`.

Release is deliberately partial. Releasing moves a hold `ACTIVE` → `RELEASED` — any other hold status fails with `ERR_PRIVACY_HOLD_NOT_ACTIVE` — and when the released hold was `FULL_SUPPRESS` and no other `ACTIVE` hold remains for the panelist, the panelist returns `SUSPENDED` → `ACTIVE`. Suppressed invitations are never restored: the compensation is partial by policy, and the panelist's contact history is otherwise untouched.

Attrition runs as a reviewable batch rather than a silent sweep. A `PanelManager` opens a refresh run with a `run_label` and an optional `attrition_grace_days` defaulting to 30; at creation the run computes `planned_attrition_count`, the number of `LAPSED` panelists whose `lapsed_at` is at least that many days in the past, while `applied_attrition_count` and `applied_forfeit_count` remain null until the run is applied. Applying executes a three-hop cascade: every grace-expired `LAPSED` panelist moves `LAPSED` → `ATTRITED`; each attrited panelist's `AUTHORIZED` awards move to `FORFEITED`; and each forfeiture credits its wave's `incentive_pool_available_cents` while debiting `incentive_pool_reserved_cents`. Each attrition also decrements the home cell's `active_count`, re-derives its status, and increments its `version`, and the run records the actual `applied_attrition_count` and `applied_forfeit_count` as it lands in `APPLIED`. Both apply and abort are possible only from `OPEN` — from any other status they fail with `ERR_REFRESH_RUN_NOT_OPEN` — and aborting moves `OPEN` → `ABORTED` with no side effects.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, including all state-transition actions, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | PanelManager |
| POST | `/feedback-panel/panel-cells` | Create a demographic quota cell | PanelManager |
| GET | `/feedback-panel/panel-cells` | List cells | PanelManager, DataAnalyst |
| GET | `/feedback-panel/panel-cells/{id}` | Get one cell | PanelManager, DataAnalyst |
| POST | `/feedback-panel/panel-cells/{id}/targets` | Adjust the cell recruitment target (OCC on cell version) | PanelManager |
| POST | `/feedback-panel/panelists` | Register a panel applicant | PanelManager |
| GET | `/feedback-panel/panelists` | List panelists | PanelManager, PrivacyOfficer |
| GET | `/feedback-panel/panelists/{id}` | Get one panelist | PanelManager, PrivacyOfficer |
| POST | `/feedback-panel/panelists/{id}/enroll` | Seat an applicant into their demographic cell | PanelManager |
| POST | `/feedback-panel/panelists/{id}/reactivate` | Reactivate a LAPSED panelist | PanelManager |
| POST | `/feedback-panel/panelists/{id}/withdraw` | Withdraw an ACTIVE or LAPSED panelist | PanelManager |
| POST | `/feedback-panel/instruments` | Create a survey instrument | SurveyDesigner |
| GET | `/feedback-panel/instruments` | List instruments | SurveyDesigner, PanelManager |
| GET | `/feedback-panel/instruments/{id}` | Get one instrument | SurveyDesigner, PanelManager, DataAnalyst |
| POST | `/feedback-panel/instruments/{id}/submit-review` | Move an instrument from DRAFT to IN_REVIEW | SurveyDesigner |
| POST | `/feedback-panel/instruments/{id}/approve` | Approve an instrument in review | SurveyDesigner |
| POST | `/feedback-panel/instruments/{id}/revise` | Return an instrument to DRAFT, bumping revision from APPROVED | SurveyDesigner |
| POST | `/feedback-panel/instruments/{id}/lock` | Lock an APPROVED instrument | SurveyDesigner |
| POST | `/feedback-panel/translations` | Create a translation at the instrument's current revision | SurveyDesigner |
| GET | `/feedback-panel/translations` | List translations | SurveyDesigner, PanelManager |
| GET | `/feedback-panel/translations/{id}` | Get one translation | SurveyDesigner |
| POST | `/feedback-panel/translations/{id}/certify` | Certify a submitted translation | SurveyDesigner |
| POST | `/feedback-panel/translations/{id}/reject` | Reject a submitted translation | SurveyDesigner |
| POST | `/feedback-panel/translations/{id}/resubmit` | Resubmit a rejected or stale translation at the current revision | SurveyDesigner |
| POST | `/feedback-panel/survey-waves` | Create a survey wave | PanelManager |
| GET | `/feedback-panel/survey-waves` | List waves | PanelManager, DataAnalyst |
| GET | `/feedback-panel/survey-waves/{id}` | Get one wave | PanelManager, DataAnalyst, PrivacyOfficer, IncentiveClerk |
| POST | `/feedback-panel/survey-waves/{id}/arm` | Arm a wave against its locked instrument | PanelManager |
| POST | `/feedback-panel/survey-waves/{id}/open-fielding` | Open fielding within the declared window | PanelManager |
| POST | `/feedback-panel/survey-waves/{id}/close` | Close fielding and run the expiry and lapse cascade | PanelManager |
| POST | `/feedback-panel/survey-waves/{id}/cancel` | Cancel a DRAFT or ARMED wave | PanelManager |
| GET | `/feedback-panel/survey-waves/{id}/analysis` | Computed analysis read: response rates and representativeness | DataAnalyst |
| POST | `/feedback-panel/invitations` | Dispatch an invitation under the contact-discipline gates | PanelManager |
| GET | `/feedback-panel/invitations` | List invitations | PanelManager |
| GET | `/feedback-panel/invitations/{id}` | Get one invitation | PanelManager |
| POST | `/feedback-panel/invitations/{id}/decline` | Record a decline on a live invitation | PanelManager |
| POST | `/feedback-panel/invitations/{id}/remind` | Send a reminder under cadence and cap rules | PanelManager |
| POST | `/feedback-panel/responses` | Submit a response against a live invitation, minting its award | PanelManager |
| GET | `/feedback-panel/responses` | List responses | PanelManager, DataAnalyst |
| GET | `/feedback-panel/responses/{id}` | Get one response | PanelManager, DataAnalyst |
| POST | `/feedback-panel/responses/{id}/accept` | Accept a submitted or quarantined response | DataAnalyst |
| POST | `/feedback-panel/responses/{id}/quarantine` | Quarantine a submitted response | DataAnalyst |
| POST | `/feedback-panel/responses/{id}/discard` | Discard a quarantined response | DataAnalyst |
| GET | `/feedback-panel/incentive-awards` | List awards | IncentiveClerk, PanelManager |
| GET | `/feedback-panel/incentive-awards/{id}` | Get one award | IncentiveClerk |
| POST | `/feedback-panel/incentive-awards/{id}/authorize` | Authorize an eligible award, reserving pool funds | IncentiveClerk |
| POST | `/feedback-panel/incentive-awards/{id}/pay` | Pay an authorized award | IncentiveClerk |
| POST | `/feedback-panel/incentive-awards/{id}/forfeit` | Forfeit an authorized award, returning funds to the pool | IncentiveClerk |
| POST | `/feedback-panel/survey-waves/{id}/weight-snapshots` | Create a weight snapshot for a closed wave (OCC on wave version) | DataAnalyst |
| GET | `/feedback-panel/weight-snapshots` | List weight snapshots | DataAnalyst, PrivacyOfficer |
| GET | `/feedback-panel/weight-snapshots/{id}` | Get one weight snapshot | DataAnalyst, PrivacyOfficer |
| POST | `/feedback-panel/weight-snapshots/{id}/finalize` | Finalize a provisional snapshot, recording the finalizer | DataAnalyst |
| POST | `/feedback-panel/publications` | Draft a publication pinning a weight snapshot | DataAnalyst |
| GET | `/feedback-panel/publications` | List publications | DataAnalyst, PrivacyOfficer, DepartmentLiaison |
| GET | `/feedback-panel/publications/{id}` | Get one publication | DataAnalyst, PrivacyOfficer, DepartmentLiaison |
| POST | `/feedback-panel/publications/{id}/publish` | Publish a draft publication after the de-identification gate | PrivacyOfficer |
| POST | `/feedback-panel/publications/{id}/retract` | Retract a published publication, suspending open commitments | PrivacyOfficer |
| POST | `/feedback-panel/follow-up-commitments` | Create a department commitment on a published publication | DepartmentLiaison |
| GET | `/feedback-panel/follow-up-commitments` | List commitments | DepartmentLiaison, PanelManager, PrivacyOfficer |
| GET | `/feedback-panel/follow-up-commitments/{id}` | Get one commitment | DepartmentLiaison, PanelManager, PrivacyOfficer |
| POST | `/feedback-panel/follow-up-commitments/{id}/start` | Start work on a commitment (own department only) | DepartmentLiaison |
| POST | `/feedback-panel/follow-up-commitments/{id}/fulfill` | Fulfill a commitment on time (own department only) | DepartmentLiaison |
| POST | `/feedback-panel/follow-up-commitments/{id}/mark-breached` | Mark an overdue commitment breached | PanelManager |
| POST | `/feedback-panel/follow-up-commitments/{id}/renegotiate` | Renegotiate a breached commitment to a new future due date (own department only) | DepartmentLiaison |
| POST | `/feedback-panel/privacy-holds` | Place a privacy hold on a panelist | PrivacyOfficer |
| GET | `/feedback-panel/privacy-holds` | List privacy holds | PrivacyOfficer, PanelManager |
| GET | `/feedback-panel/privacy-holds/{id}` | Get one privacy hold | PrivacyOfficer, PanelManager |
| POST | `/feedback-panel/privacy-holds/{id}/release` | Release an active hold, reactivating the panelist when none remain | PrivacyOfficer |
| POST | `/feedback-panel/refresh-runs` | Open a refresh run and preview planned attrition | PanelManager |
| GET | `/feedback-panel/refresh-runs/{id}` | Get one refresh run | PanelManager |
| POST | `/feedback-panel/refresh-runs/{id}/apply` | Apply the refresh run, attriting lapsed panelists and forfeiting awards | PanelManager |
| POST | `/feedback-panel/refresh-runs/{id}/abort` | Abort an open refresh run | PanelManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_FORBIDDEN_DEPARTMENT` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PANEL_CELL_NOT_FOUND` | 404 |
| `ERR_PANELIST_NOT_FOUND` | 404 |
| `ERR_INSTRUMENT_NOT_FOUND` | 404 |
| `ERR_TRANSLATION_NOT_FOUND` | 404 |
| `ERR_WAVE_NOT_FOUND` | 404 |
| `ERR_INVITATION_NOT_FOUND` | 404 |
| `ERR_RESPONSE_NOT_FOUND` | 404 |
| `ERR_AWARD_NOT_FOUND` | 404 |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 |
| `ERR_PUBLICATION_NOT_FOUND` | 404 |
| `ERR_COMMITMENT_NOT_FOUND` | 404 |
| `ERR_PRIVACY_HOLD_NOT_FOUND` | 404 |
| `ERR_REFRESH_RUN_NOT_FOUND` | 404 |
| `ERR_STALE_WAVE_VERSION` | 412 |
| `ERR_STALE_CELL_VERSION` | 412 |
| `ERR_WAVE_NOT_FIELDING` | 409 |
| `ERR_WAVE_INVALID_STATE` | 409 |
| `ERR_WAVE_NOT_ARMED` | 409 |
| `ERR_WAVE_NOT_CLOSED` | 409 |
| `ERR_WAVE_NOT_WEIGHTED` | 409 |
| `ERR_WAVE_ALREADY_TERMINAL` | 409 |
| `ERR_INSTRUMENT_NOT_LOCKED` | 409 |
| `ERR_INSTRUMENT_NOT_IN_REVIEW` | 409 |
| `ERR_INSTRUMENT_INVALID_STATE` | 409 |
| `ERR_TRANSLATION_INVALID_STATE` | 409 |
| `ERR_TRANSLATION_STALE_REVISION` | 409 |
| `ERR_TRANSLATION_NOT_CERTIFIED` | 409 |
| `ERR_PANELIST_NOT_LAPSED` | 409 |
| `ERR_PANELIST_NOT_ACTIVE` | 409 |
| `ERR_INVITATION_NOT_OPEN` | 409 |
| `ERR_RESPONSE_NOT_REVIEWABLE` | 409 |
| `ERR_AWARD_NOT_AUTHORIZED_STATE` | 409 |
| `ERR_AWARD_NOT_PAID_STATE` | 409 |
| `ERR_AWARD_NOT_FORFEIT_STATE` | 409 |
| `ERR_SNAPSHOT_SUPERSEDED` | 409 |
| `ERR_SNAPSHOT_NOT_FINALIZED` | 409 |
| `ERR_PUBLICATION_NOT_PUBLISHED` | 409 |
| `ERR_COMMITMENT_NOT_OPEN` | 409 |
| `ERR_PRIVACY_HOLD_NOT_ACTIVE` | 409 |
| `ERR_REFRESH_RUN_NOT_OPEN` | 409 |
| `ERR_PRIVACY_HOLD_ACTIVE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_WAVE_WINDOW_NOT_OPEN` | 409 |
| `ERR_CONTACT_WASHOUT_VIOLATION` | 409 |
| `ERR_REMINDER_CADENCE_TOO_SOON` | 409 |
| `ERR_REMINDER_CAP_REACHED` | 409 |
| `ERR_COMMITMENT_OVERDUE` | 409 |
| `ERR_COMMITMENT_NOT_OVERDUE` | 409 |
| `ERR_DUPLICATE_INVITATION` | 409 |
| `ERR_CELL_SATURATED` | 409 |
| `ERR_CELL_CONTACT_CAP_REACHED` | 409 |
| `ERR_PRIVACY_HOLD_EXISTS` | 409 |
| `ERR_DUPLICATE_TRANSLATION` | 409 |
| `ERR_K_ANONYMITY_VIOLATION` | 422 |
| `ERR_WEIGHTS_NOT_COMPUTABLE` | 422 |
| `ERR_MIN_RESPONSE_NOT_MET` | 409 |
| `ERR_INCENTIVE_POOL_INSUFFICIENT` | 402 |
