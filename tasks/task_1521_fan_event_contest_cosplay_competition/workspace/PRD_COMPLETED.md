# Fan Contest Cosplay Ops API — Product Requirements Document

## 1. Introduction

Fan conventions run some of their most technically demanding programming inside the masquerade and craftsmanship contest track. A single weekend contest can involve hundreds of cosplayers across multiple skill divisions, craftsmanship pre-judging panels, a tightly choreographed stage walk with lighting and audio cues, prop and weapon safety inspections at check-in, cash-prize disbursement with tax reporting obligations, and green-room logistics that must respect accessibility commitments. Today most of this is run from spreadsheets, walkie-talkies, and sticky notes, which is why scoring sheets go missing, safety re-inspections fail to pull entries off the stage queue, and prize paperwork falls behind.

This document specifies the Fan Contest Cosplay Ops API, the backend service used by the programming team to operate that workflow end to end. The API tracks the contest lifecycle from initial setup through registration, craftsmanship pre-judging, stage performance, tabulation, and prize disbursement, while enforcing prop and weapon safety policy, media-consent gating for the livestream broadcast, segregation of duties on prize finance, and accessibility-aware green-room booking. Readers are expected to implement the service so that every rule in this document is honored exactly; the narrative deliberately spreads related rules across the subsections where they naturally belong, and the endpoint catalogue in §4 is a summary rather than a contract in itself.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers: `X-User-ID`, which identifies the acting caller, and `X-User-Role`, which names the caller's operational capacity. The system recognizes seven roles, spelled exactly as follows: `Anonymous`, `Contestant`, `ContestLead`, `Judge`, `SafetyOfficer`, `StageManager`, and `Treasurer`. A request missing either header, or presenting an `X-User-Role` value not in this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The interpretation of `X-User-ID` differs by role. When `X-User-Role` is `Contestant`, `X-User-ID` is the `id` of the acting `Contestant`; ownership checks on any resource that references a `Contestant` compare the resource's foreign-key field (such as `contestant_id`) to `X-User-ID`. When `X-User-Role` is `Judge`, `X-User-ID` is the `id` of the acting `Judge`; ownership checks on any resource that references a `Judge` compare the resource's foreign-key field (such as `judge_id`) to `X-User-ID`. When `X-User-Role` is `Anonymous`, `ContestLead`, `SafetyOfficer`, `StageManager`, or `Treasurer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` or `approved_by_user_id` on a `PrizeAward`) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter controls the maximum number of items returned; it defaults to 10, has a minimum of 1, and has a maximum of 100. The `offset` parameter controls the number of items skipped before the page begins and defaults to 0. Non-integer parameter values fall back to the defaults, and out-of-range values are clamped to the nearest bound (`limit` into [1, 100], `offset` up to 0) rather than rejected. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. Common Resource Properties and Mutation Semantics

Every top-level resource — `ContestEvent`, `Category`, `Contestant`, `Judge`, `Entry`, `PreJudgingSlot`, `ScoreSheet`, `PerformanceSlot`, `PrizeAward`, and `GreenRoomBooking` — carries four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, set once at creation. `updated_at` is an ISO 8601 UTC timestamp initialized equal to `created_at` and refreshed on every mutation of the resource. `version` is an integer that starts at 1 at creation and increments on every mutation. Cascade-driven changes (a contest transition flipping every category, a tabulation reopen clearing every sibling placement, a sequence compaction rewriting `sequence_number` on remaining queue slots) are mutations of each affected resource and therefore bump each affected resource's `version` and refresh each affected resource's `updated_at`, not just the parent's.

### 2.5. Monetary Values and Precision

All money in the system is expressed in integer cents; no fractional cents appear anywhere. Wherever a division or rate multiplication would produce a fraction of a cent (the purse split, backup withholding), the result is rounded to integer cents using the round-half-up method. Scores, by contrast, are decimal numbers: every per-sheet total and every entry-level aggregate is rounded half-up to exactly two decimal places, and the rounding is applied at each step (first per scoresheet, then per entry mean) rather than deferred to a final result.

### 2.6. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and only those two. A category edit request may carry `expected_category_version`; when the field is present it must be an integer (a non-integer value is `ERR_VALIDATION`), and if it does not equal the category's current `version` (because another lead changed the configuration, or a contest-level cascade bumped the category), the request is rejected with `ERR_STALE_VERSION` (HTTP 412); when the field is absent, no OCC check is applied. An entry edit request likewise may carry `expected_entry_version` under the same rules; if the entry's current `version` has advanced past the supplied value (because a safety re-inspection wrote a new verdict, for example), the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not accept a version field and apply no OCC check.

### 2.7. The Logical Clock

The server maintains a logical clock distinct from wall-clock time. Before any operator call sets it, the logical clock is exactly `2026-08-01T00:00:00Z`; the server must never fall back to wall-clock time. A contest-lead-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; any parseable ISO 8601 instant is accepted with no monotonicity constraint, and a missing or unparseable `to_iso8601` is rejected with `ERR_VALIDATION`. On success the capability responds with the new logical-now carried in a `current_utc` field of the response `data` object, serialized as an ISO 8601 UTC timestamp with three fractional digits per the §2.4 convention. The logical clock is the reference for the green-room "not in the past" check that rejects a booking whose `start_at` precedes logical now with `ERR_BOOKING_IN_PAST`, and it supplies the timestamps written to `created_at` and `updated_at` across the system.

### 2.8. Validation Order

When several rules could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN`), then field-shape validation such as missing fields, bad types, bad enums, and out-of-range scores (`ERR_VALIDATION`), then path-id and body-foreign-key resolution in left-to-right order (`ERR_NOT_FOUND`), then ownership (`ERR_NOT_OWNER`), then the optimistic-concurrency check on the two endpoints of §2.6 (`ERR_STALE_VERSION`), then state-machine preconditions and phase gates (`ERR_INVALID_STATE` and the state-specific codes `ERR_REGISTRATION_NOT_OPEN`, `ERR_CATEGORY_NOT_TABULATED`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SCORESHEETS_NOT_LOCKED`, `ERR_NO_ELIGIBLE_ENTRIES`), then business-safety gates (`ERR_PROP_BANNED`, `ERR_SAFETY_NOT_APPROVED`, `ERR_CONSENT_REQUIRED`), then business-referential checks (`ERR_JUDGE_CONFLICT`, `ERR_DUPLICATE_SCORESHEET`, `ERR_ENTRY_CATEGORY_MISMATCH`, and the judge-panel assignment check that surfaces as `ERR_FORBIDDEN`), then business constraints (`ERR_CATEGORY_FULL`, `ERR_DUPLICATE_ENTRY`, `ERR_DIVISION_AGE_INELIGIBLE`, `ERR_SEQUENCE_CONFLICT`, `ERR_GREEN_ROOM_INACCESSIBLE`, `ERR_SEGREGATION_OF_DUTIES`), then temporal rules (`ERR_SLOT_OUTSIDE_WINDOW`, `ERR_BOOKING_IN_PAST`, `ERR_SLOT_OVERLAP`, `ERR_GREEN_ROOM_FULL`), and finally fiscal rules (`ERR_PRIZE_BUDGET_EXCEEDED`, `ERR_TAX_FORM_REQUIRED`). Within each tier the rules in §3 name the specific check that applies to each endpoint.

### 2.9. Hierarchical Consistency and Cascades

The system maintains alignment between parent and child resources automatically, without requiring the client to issue compensating calls. When a contest is cancelled, every non-terminal entry of the contest moves to `WITHDRAWN`, every booked pre-judging slot tied to those entries returns to `OPEN` with its `booked_entry_id` cleared, every stage slot still `QUEUED` is marked `SKIPPED` without resequencing (an `ON_STAGE` slot is left untouched, and the contest is over, so compaction is moot), and every `BOOKED` green-room booking of the contest is `CANCELLED`. When a scoresheet is reopened or a placed entry is disqualified inside a `TABULATED` category, the category automatically reverts to `SCORING` and all of its `PLACED` entries revert to `PERFORMED` with their placement fields cleared; if the parent contest had already advanced to `TABULATION`, the contest itself auto-reverts to `JUDGING`. These cascades are part of the contract, and each affected resource's `version` and `updated_at` move accordingly.

### 2.10. Nested Resource Retrieval

Endpoints whose path carries more than one identifier validate path parameters left-to-right, returning `ERR_NOT_FOUND` for the first identifier that does not resolve. A request that targets a child under a nonexistent parent never reaches child validation.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Contest and Its Categories

A `ContestLead` begins by creating a `ContestEvent` with a human-readable `name`, a contest window bracketed by `start_at` and `end_at` (both ISO 8601 UTC, with `end_at` strictly after `start_at`), a total `prize_budget_cents` that must be at least zero, and an optional `max_entries_per_contestant` defaulting to 2 that caps how many non-terminal entries a single contestant may hold in this contest (and must be at least 1). Violations of these creation-time shape rules — an `end_at` not strictly after `start_at`, a negative `prize_budget_cents`, or a `max_entries_per_contestant` below 1 — are rejected with `ERR_VALIDATION`. The new contest starts in `SETUP` status. Alongside `prize_budget_cents`, every contest exposes two computed budget fields: `budget_reserved_cents`, the sum of `value_cents` over the contest's `PrizeAward` records whose status is `PENDING`, `APPROVED`, `DISBURSED`, or `TAX_REPORTED`; and `budget_available_cents`, the difference between `prize_budget_cents` and `budget_reserved_cents`. The invariant `prize_budget_cents == budget_reserved_cents + budget_available_cents` holds at all times.

Within a contest, the lead defines one `Category` per competitive bracket, supplying `contest_id`, a `name` such as Armor or Needlework, a `skill_division` of `JUNIOR`, `NOVICE`, `JOURNEYMAN`, or `MASTERS`, a `max_entries` quota of at least 1, a `tabulation_method` of `WEIGHTED_MEAN` or `TRIMMED_MEAN`, and a `prize_purse_cents` of at least zero. The category starts in `DRAFT`; categories may be created at any time, regardless of the parent contest's status. At creation (and again whenever `prize_purse_cents` is edited), the system computes the purse split and stores it as three integer-cent fields. The rounding order is pinned: `prize_rank1_cents` is the purse multiplied by 0.50 and rounded half-up to integer cents; `prize_rank2_cents` is the purse multiplied by 0.30 and rounded half-up to integer cents; `prize_rank3_cents` is the remainder, computed as the purse minus rank 1 minus rank 2 so that rounding drift is absorbed by third place. Rounding the third rank independently is forbidden — for a purse of 9999 cents the correct split is 5000, 3000, and 1999, not 5000, 3000, and 2000. Ranks beyond third place receive nothing. A category also carries a computed `entry_count`: the number of its entries whose status is neither `WITHDRAWN` nor `DISQUALIFIED`.

Category configuration is editable only while the parent contest is still in `SETUP`. An edit may touch `name`, `skill_division`, `max_entries`, `tabulation_method`, or `prize_purse_cents`, and must carry `expected_category_version` per the OCC rule in §2.6; a `prize_purse_cents` change recomputes the split above. Once the contest leaves `SETUP`, category configuration is frozen.

Opening registration is a single lead-driven transition on the contest from `SETUP` to `REGISTRATION_OPEN`, invoked by posting a `to` field naming the desired target state. The precondition is that at least one category exists for the contest, otherwise the request is rejected with `ERR_INVALID_STATE`. As a side effect, every `DRAFT` category of the contest flips to `OPEN`, bumping each category's `version`. Registration is later closed by a transition with `to` set to `REGISTRATION_CLOSED` from `REGISTRATION_OPEN`, and judging begins with a transition whose `to` is `JUDGING` from `REGISTRATION_CLOSED` which flips every `OPEN` category of the contest to `SCORING`, again bumping each category's `version`. A contest in `SETUP`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED` may instead be cancelled outright by posting `to` as `CANCELLED`; the cancellation cascade of §2.9 applies. `CANCELLED` and `COMPLETED` are terminal states with no outgoing transitions; any transition attempt from them is rejected with `ERR_INVALID_STATE`.

### 3.2. Contestants, Judges, and Consent

Anyone may self-register a contestant profile — this is the one operation available to the `Anonymous` role — by supplying `full_name`, `email`, `birth_date` in `YYYY-MM-DD` form, and an optional `accessibility_needs` list (free-form values such as `WHEELCHAIR` or `ASL_INTERPRETER`, defaulting to empty). The `email` must be unique across contestants; a duplicate is rejected with `ERR_VALIDATION`. A contestant record also carries a system-managed `consents` list; each item has a `scope` of `PHOTOGRAPHY`, `VIDEO`, or `LIVESTREAM`, a `status` of `GRANTED` or `REVOKED`, and an `updated_at` timestamp, with at most one item per scope. The owning `Contestant` grants or revokes one scope at a time by posting a `scope` together with a `granted` boolean; this is a cyclic upsert that creates the item if absent, flips its `status` if present, and bumps the contestant's `version`. A contestant's own profile may be read back by the contestant or by a `ContestLead`; a `Contestant` attempting to read another contestant's profile is rejected with `ERR_NOT_OWNER`.

Judges are onboarded by a `ContestLead`, who supplies the `contest_id` of the panel, a `display_name`, a non-empty `category_ids` list naming the categories this judge may score, and an optional `linked_contestant_id` (default null) for the common case where a judge also competes. Every id in `category_ids`, and a non-null `linked_contestant_id`, must resolve to an existing resource, otherwise the request is rejected with `ERR_NOT_FOUND`. The `linked_contestant_id` drives the conflict-of-interest check described in §3.5. The reverse lookup — which judges are linked to a given contestant — is available to the lead, as is the panel roster of a contest to the lead and to judges.

### 3.3. Registration, Safety Check-in, and the Entry Lifecycle

A contestant registers an `Entry` by posting their own `contestant_id`, the target `category_id`, a `title`, a `prop_declarations` list describing the prop types involved (for example `FOAM_WEAPON` or `ARMOR`), an optional `character_source` naming the source media (default empty), and an optional `requires_prejudging` flag (default true) that declares whether the craftsmanship panel must see the build before the stage walk. The contest is denormalized onto the entry as `contest_id` at creation time. The request must originate from the contestant themselves — a body `contestant_id` that does not equal the caller's `X-User-ID` is rejected with `ERR_NOT_OWNER` — and entry creation is permitted only while the parent contest is `REGISTRATION_OPEN` and the target category is `OPEN`, otherwise `ERR_REGISTRATION_NOT_OPEN`.

Three business constraints guard registration, evaluated after the safety screening of the declared props. First, `prop_declarations` must not include any banned prop type — `LIVE_STEEL`, `FIREARM`, or `PYROTECHNICS` — or the request is rejected with `ERR_PROP_BANNED` (HTTP 422). Second, capacity: if the category's current `entry_count` already equals its `max_entries`, the request is rejected with `ERR_CATEGORY_FULL` (the boundary is inclusive — exactly at quota rejects). Third, per-contestant limits: if the contestant already holds a non-terminal entry in the same category, or already holds `max_entries_per_contestant` non-terminal entries anywhere in the contest, the request is rejected with `ERR_DUPLICATE_ENTRY`. Finally, when the category's `skill_division` is `JUNIOR`, the contestant's age is checked: age is the number of full calendar years between `birth_date` and the date part of the contest's `start_at`, where a birthday falling exactly on the contest date counts as already completed. Eligibility requires the age to be strictly less than 16; a contestant whose sixteenth birthday falls on or before the contest date is rejected with `ERR_DIVISION_AGE_INELIGIBLE` (HTTP 422).

A fresh entry lands in `SUBMITTED` with `safety_status` set to `PENDING` and `rejected_props` empty. At check-in, a `SafetyOfficer` records a prop and weapon policy `verdict` of `APPROVED` or `REJECTED`. An approval of a `SUBMITTED` entry moves it to `SAFETY_APPROVED`, sets `safety_status` to `APPROVED`, and clears `rejected_props` to empty. A rejection moves a `SUBMITTED` entry to `SAFETY_REJECTED`, sets `safety_status` to `REJECTED`, and records the request's `rejected_props` list (which may be empty). Re-inspection is supported: an entry already in `SAFETY_APPROVED` may be rejected again — for instance when a contestant swaps a prop on the convention floor — which sets `safety_status` to `REJECTED`, stores the new `rejected_props`, and force-releases any `BOOKED` pre-judging slot the entry held back to `OPEN` with its `booked_entry_id` cleared. An approval verdict is accepted only while the entry is `SUBMITTED`, and a rejection verdict only while the entry is `SUBMITTED` or `SAFETY_APPROVED`; any other verdict-versus-state combination — including approving an entry already in `SAFETY_APPROVED`, or any safety-check request against an entry in `PREJUDGED`, `STAGE_QUEUED`, or a later state — is rejected with `ERR_INVALID_STATE`. Note that releasing a booked pre-judging slot leaves the entry's own status untouched (§3.4), so release alone does not make a `PREJUDGED` entry re-inspectable.

A contestant whose entry was safety-rejected may edit the entry — changing `title`, `character_source`, or `prop_declarations` — while it is in `SUBMITTED` or `SAFETY_REJECTED`. The edit must carry `expected_entry_version` per §2.6. When a `prop_declarations` change lands on a `SAFETY_REJECTED` entry, the entry cycles back to `SUBMITTED` with `safety_status` reset to `PENDING` and `rejected_props` cleared; an edit that does not change `prop_declarations` leaves the status alone. Banned prop types are screened on edit exactly as at creation, so introducing `LIVE_STEEL`, `FIREARM`, or `PYROTECHNICS` through an edit is likewise rejected with `ERR_PROP_BANNED`.

Withdrawal is the contestant's own exit and is permitted from `SUBMITTED`, `SAFETY_REJECTED`, `SAFETY_APPROVED`, `PREJUDGED`, or `STAGE_QUEUED`; attempts from any other state are rejected with `ERR_INVALID_STATE`. Withdrawal cascades: any `BOOKED` pre-judging slot of the entry returns to `OPEN` with `booked_entry_id` cleared, and any `QUEUED` or `ON_STAGE` stage slot of the entry is marked `SKIPPED`, after which the remaining `QUEUED` stage slots of the contest are resequenced per the compaction rule in §3.6. Disqualification, by contrast, is a `ContestLead` action available from any non-terminal entry state, carrying an optional `reason` (accepted but not persisted anywhere), and its cascade is broader — see §3.5 and §3.7.

### 3.4. Craftsmanship Pre-Judging

The craftsmanship review happens before the stage walk for any entry with `requires_prejudging` true. A `ContestLead` defines a `PreJudgingSlot` by supplying `category_id`, a `panel_name` identifying the judging panel, and a `[start_at, end_at]` window with `end_at` strictly after `start_at` (an `end_at` not strictly after `start_at` is rejected with `ERR_VALIDATION`). The slot must lie entirely within its contest's window: the slot's `start_at` must be on or after the contest's `start_at` and the slot's `end_at` must be on or before the contest's `end_at`, otherwise the request is rejected with `ERR_SLOT_OUTSIDE_WINDOW` (HTTP 422). Within a given `(category_id, panel_name)` pair, slot windows may not overlap — two slots overlap when each starts before the other ends, with half-open adjacency allowed so a slot beginning exactly when another ends is legal; a violating request is rejected with `ERR_SLOT_OVERLAP`.

A slot is born `OPEN`. A contestant books an `OPEN` slot by naming the `entry_id` of one of their own entries; the entry must be in `SAFETY_APPROVED` (safety must clear before craftsmanship review — anything else is `ERR_INVALID_STATE`), the entry's `category_id` must equal the slot's `category_id` (otherwise `ERR_ENTRY_CATEGORY_MISMATCH`), and the entry must not already hold another `BOOKED` slot; a slot that is not `OPEN`, or an entry already holding a `BOOKED` slot, is rejected with `ERR_INVALID_STATE`. Booking writes the entry id into `booked_entry_id`. A booked slot can be released — by the contestant who owns the booked entry (anyone else drawing `ERR_NOT_OWNER`), by a `ContestLead` marking a no-show, or by system cascade — which returns it to `OPEN`, clears `booked_entry_id`, and leaves the entry's own status untouched so it may rebook. Releasing a slot that is not `BOOKED` is rejected with `ERR_INVALID_STATE`. When the panel finishes, a `ContestLead` completes a `BOOKED` slot, which advances the booked entry from `SAFETY_APPROVED` to `PREJUDGED`. `COMPLETED` is terminal for the slot.

### 3.5. Scoring and Tabulation

Judges score entries through `ScoreSheet` records. Creating a scoresheet takes `entry_id`, a `phase` of `CRAFTSMANSHIP` or `STAGE`, and three integer criterion scores — `craftsmanship`, `accuracy`, and `presentation` — each between 0 and 10 inclusive; a score outside that range is a validation error. The acting judge's `judge_id` is taken from the caller's `X-User-ID` — if no persisted `Judge` has that id, the request is rejected with `ERR_NOT_FOUND` — and the entry's `category_id` is denormalized onto the sheet at creation. Phase gates apply at the state tier: a `CRAFTSMANSHIP` sheet may be created only for an entry that is `PREJUDGED`, and a `STAGE` sheet only for an entry that is `STAGE_QUEUED` or `PERFORMED`. Three referential checks follow, all at the same priority tier. The judge's `category_ids` must contain the entry's category, otherwise the request is rejected with `ERR_FORBIDDEN`. If the judge has a `linked_contestant_id` and that contestant holds a non-terminal entry in the scoresheet entry's category, the request is rejected with `ERR_JUDGE_CONFLICT`. And if a non-`VOID` scoresheet already exists for the same `(judge_id, entry_id, phase)` triple, the request is rejected with `ERR_DUPLICATE_SCORESHEET`.

At creation the system computes and stores `sheet_total`: half the `craftsmanship` score plus three-tenths of the `accuracy` score plus one-fifth of the `presentation` score, rounded half-up to two decimal places. A sheet starts in `DRAFT`. The owning judge submits their own `DRAFT` sheet — anyone else drawing `ERR_NOT_OWNER` — moving it to `SUBMITTED`. A `ContestLead` then locks the entire category in bulk: while the category is `SCORING` (otherwise `ERR_INVALID_STATE`), every `SUBMITTED` sheet of every entry in the category moves to `LOCKED`; the response `data` carries `locked_count`, the number of sheets moved. Should a correction be needed afterward, the lead may reopen a `LOCKED` sheet, returning it to `SUBMITTED`; if the sheet's category had already been tabulated, this reopen is one of the two triggers of the tabulation reopen cascade described below.

Tabulation is the lead-driven transition that moves a `SCORING` category to `TABULATED`; the call responds with a `data` object carrying `placed_entry_count` (the number of entries ranked) and `category_id`, rather than the category resource. Two preconditions apply, in order: first, no scoresheet of any entry in the category may remain in `DRAFT` or `SUBMITTED`, otherwise the request is rejected with `ERR_SCORESHEETS_NOT_LOCKED`; second, at least one entry of the category must be in `PERFORMED`, otherwise `ERR_NO_ELIGIBLE_ENTRIES`. Tabulation then computes, for each `PERFORMED` entry, the entry's `final_score` and `craftsmanship_mean`. The input set is the entry's `LOCKED` scoresheets — `DRAFT`, `SUBMITTED`, and `VOID` sheets are excluded — pooling both phases with equal weight per sheet. A `PERFORMED` entry with no `LOCKED` scoresheets receives null `final_score` and null `craftsmanship_mean`, sorts below every scored entry in the placement ordering, and still receives a `placement_rank`. Under the `WEIGHTED_MEAN` variant, `final_score` is the mean of `sheet_total` over that set, rounded half-up to two decimal places. Under the `TRIMMED_MEAN` variant, when the set holds at least three sheets, exactly one highest `sheet_total` and exactly one lowest `sheet_total` are discarded (on ties only one instance of the extreme value is dropped) before the same rounded mean is taken over the remainder; when the set holds fewer than three sheets, `TRIMMED_MEAN` falls back to the plain `WEIGHTED_MEAN` result. The `craftsmanship_mean` is the mean of the raw `craftsmanship` criterion across the same locked set, rounded half-up to two decimal places, and exists purely as the placement tie-breaker.

Placement ranks are then assigned across the category's `PERFORMED` entries. Entries are ordered by `final_score` descending; ties break by `craftsmanship_mean` descending; further ties break by `created_at` ascending; `id` is never used as a tie-break. In that order, `placement_rank` is assigned 1 through N gap-free, and each ranked entry moves from `PERFORMED` to `PLACED`. Entries of the category that are neither `PERFORMED` nor in a terminal state keep their status and have `placement_rank` null.

A tabulated category is not irreversible. The tabulation reopen cascade fires when either a scoresheet of a category entry is reopened out of `LOCKED`, or a `PLACED` entry of the category is disqualified. The category auto-reverts from `TABULATED` to `SCORING`; every `PLACED` entry of the category reverts to `PERFORMED` with `placement_rank`, `final_score`, and `craftsmanship_mean` all cleared to null; and, as a bubble-up, if the parent contest was sitting in `TABULATION`, the contest itself auto-reverts from `TABULATION` to `JUDGING`. On the contest side, the forward `JUDGING` to `TABULATION` transition is gated on every category of the contest having reached `TABULATED`, surfacing `ERR_INVALID_STATE` otherwise, and the terminal `TABULATION` to `COMPLETED` transition closes out the contest.

### 3.6. The Stage Walk

Stage operations are owned by the `StageManager`. Queuing an entry onto the stage order creates a `PerformanceSlot` carrying `entry_id`, a 1-based `sequence_number`, a planned `duration_seconds` of at least 1, and optional `tech_cues` for the lighting and audio crew (default empty); the entry's `contest_id` is denormalized onto the slot. Four tiers of gates apply, in this order. State first: the entry must be in `SUBMITTED`, `SAFETY_REJECTED`, `SAFETY_APPROVED`, or `PREJUDGED`, and either `requires_prejudging` must be false or the entry must actually be `PREJUDGED` — anything else is `ERR_INVALID_STATE`. Safety next: the entry's `safety_status` must be `APPROVED`, otherwise `ERR_SAFETY_NOT_APPROVED`. Consent next: because every stage performance is carried on the livestream, the entry's contestant must hold a consent item with `scope` `LIVESTREAM` and `status` `GRANTED`, otherwise `ERR_CONSENT_REQUIRED`. Constraint last: the requested `sequence_number` must be unique among the contest's slots currently in `QUEUED` or `ON_STAGE`, and the entry must not already occupy another `QUEUED` or `ON_STAGE` slot — a violation is `ERR_SEQUENCE_CONFLICT`. Successful queuing moves a `SAFETY_APPROVED` or `PREJUDGED` entry to `STAGE_QUEUED`.

While a slot is `QUEUED`, the stage manager may adjust its `sequence_number`, `duration_seconds`, or `tech_cues`; sequence changes are held to the same uniqueness rule and surface `ERR_SEQUENCE_CONFLICT`. The stage walk itself is driven by posting a `to` field naming the desired next state. Advancing with `to` set to `ON_STAGE` from `QUEUED` requires that no other slot of the contest is currently `ON_STAGE` and that the entry is `STAGE_QUEUED` (violations of either surface as `ERR_INVALID_STATE`), that `safety_status` is `APPROVED` (else `ERR_SAFETY_NOT_APPROVED`), and that the contestant's `LIVESTREAM` consent is `GRANTED` (else `ERR_CONSENT_REQUIRED`). Advancing with `to` set to `COMPLETED` from `ON_STAGE` then moves the entry from `STAGE_QUEUED` to `PERFORMED`. A slot may instead be skipped by posting `to` as `SKIPPED`, from either `QUEUED` or `ON_STAGE`. A skip regresses the entry out of `STAGE_QUEUED`: back to `PREJUDGED` when the entry's `requires_prejudging` is true (requeueing is allowed), or back to `SAFETY_APPROVED` when it is false. Every skip triggers stage sequence compaction across the contest: the remaining `QUEUED` slots are ordered by `sequence_number` ascending with `created_at` ascending as the tie-break (never `id`), and `sequence_number` is reassigned 1 through N gap-free in that order, each reassignment bumping the slot's `version`.

### 3.7. Prize Awards, Withholding, and Tax Reporting

Once a category is `TABULATED`, a `Treasurer` may create a `PrizeAward` for one of its ranks by supplying `category_id` and a `rank` between 1 and 3 inclusive. Creating against a category not yet `TABULATED` is rejected with `ERR_CATEGORY_NOT_TABULATED`. The entry being awarded is selected automatically: the `PLACED` entry of the category whose `placement_rank` equals the requested `rank`, with an empty result rejected as `ERR_PLACEMENT_NOT_FOUND`. The award's `value_cents` is snapshotted at creation from the category's purse split — `prize_rank1_cents`, `prize_rank2_cents`, or `prize_rank3_cents` according to rank — so later edits to the purse never rewrite an existing award. The contest is denormalized onto the award as `contest_id`. Two fiscal rules attach at creation. First, the award reserves budget: `budget_reserved_cents` increases by `value_cents`, and if the new total would exceed the contest's `prize_budget_cents`, the request is rejected with `ERR_PRIZE_BUDGET_EXCEEDED` (HTTP 422). Second, tax flagging: `tax_reportable` is computed as whether `value_cents` is greater than or equal to 60000 cents — the boundary is inclusive, so a prize of exactly 60000 is reportable. The award also records `created_by_user_id`, the `X-User-ID` of the creating treasurer. On a fresh award `tax_form_received` is false and `withheld_cents` and `net_payout_cents` are null, remaining so until disbursement.

A new award starts `PENDING`. Approval by a `Treasurer` moves it to `APPROVED` and writes the approver's `X-User-ID` into `approved_by_user_id`, but segregation of duties forbids the maker from checking their own work: if the caller's `X-User-ID` equals the award's `created_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Disbursement moves an `APPROVED` award to `DISBURSED` and takes a single input, `tax_form_received`, recording whether the winner's W-9 is on file. When `tax_form_received` is true, `withheld_cents` is set to 0 and `net_payout_cents` equals the full `value_cents`. When `tax_form_received` is false, backup withholding applies: `withheld_cents` is the `value_cents` multiplied by 0.24, rounded half-up to integer cents, and `net_payout_cents` is the `value_cents` minus `withheld_cents`. The same gross value therefore produces different net payouts across the two variants.

A `DISBURSED` award may be marked `TAX_REPORTED` once its 1099 has been filed. Two preconditions guard that step: the award's `tax_reportable` must be true (sub-threshold prizes are never reported, and the attempt is rejected with `ERR_INVALID_STATE`), and `tax_form_received` must be true — a 1099 cannot be filed without a W-9, and the attempt is rejected with `ERR_TAX_FORM_REQUIRED`. Revocation is the exit in the other direction: a `ContestLead` may revoke an award in `PENDING` or `APPROVED`, moving it to `REVOKED` and restoring budget by subtracting `value_cents` from `budget_reserved_cents` so the budget invariant of §3.1 holds. Awards that have reached `DISBURSED` or `TAX_REPORTED` cannot be revoked — the money is already out the door — and are untouched by every cascade.

For finance review, a contest exposes a computed tax summary readable by `Treasurer` and `ContestLead`. It aggregates only the contest's awards in `DISBURSED` or `TAX_REPORTED` — `PENDING`, `APPROVED`, and `REVOKED` are excluded because that money has not left (or will never leave) the building — and reports `total_prize_value_cents` as the sum of `value_cents`, `total_withheld_cents` as the sum of the per-award `withheld_cents` exactly as rounded at disburse time with no re-rounding at aggregation, `reportable_award_count` as the number of included awards whose `tax_reportable` is true, and `disbursed_award_count` as the number of awards in the input set.

### 3.8. Disqualification and Its Cascade

Disqualification by a `ContestLead` is the most far-reaching action in the system and is permitted from any entry state other than `WITHDRAWN` or `DISQUALIFIED` (otherwise `ERR_INVALID_STATE`). Its cascade has three chained links plus a direct fan-out. Link one: every scoresheet of the entry in `DRAFT`, `SUBMITTED`, or `LOCKED` is voided, moving it to the terminal `VOID` state. Link two: voiding sheets breaks the locked-sheet completeness of a `TABULATED` category, so the tabulation reopen cascade of §3.5 fires — the category reverts to `SCORING` and sibling placements are cleared. Link three: a category leaving `TABULATED` breaks the all-categories-tabulated invariant of a contest in `TABULATION`, so the contest auto-reverts to `JUDGING`. In parallel, the direct fan-out releases resources: any `BOOKED` pre-judging slot of the entry returns to `OPEN` with `booked_entry_id` cleared; any `QUEUED` or `ON_STAGE` performance slot of the entry is marked `SKIPPED` followed by stage sequence compaction; and any prize award of the entry still in `PENDING` or `APPROVED` is revoked with its `value_cents` restored to the contest budget. When the disqualified entry was itself `PLACED`, its `placement_rank` is cleared as part of the revert.

### 3.9. Green-Room Booking

Contestants book green-room time for costume changes and repairs. Creating a `GreenRoomBooking` takes the caller's own `contestant_id`, the `contest_id`, a `room_name` of `NORTH`, `SOUTH`, or `EAST`, a `[start_at, end_at]` window with `end_at` strictly after `start_at` (an `end_at` not strictly after `start_at` is rejected with `ERR_VALIDATION`), and an optional `requires_accessibility_setup` flag defaulting to false. Ownership is enforced as usual — a body `contestant_id` that does not match the caller's `X-User-ID` is rejected with `ERR_NOT_OWNER`. The window may not begin in the past relative to the logical clock of §2.7, otherwise `ERR_BOOKING_IN_PAST` (HTTP 422). Accessibility is enforced structurally: only `EAST` is accessibility-equipped, so a request with `requires_accessibility_setup` true and any other `room_name` is rejected with `ERR_GREEN_ROOM_INACCESSIBLE` (HTTP 422).

Capacity is enforced per room by overlap count. Two bookings overlap when neither ends on or before the other's start — equivalently, adjacency where one booking's `end_at` equals the other's `start_at` does not count as an overlap. Counting the new request against existing `BOOKED` bookings in the same room, the request is rejected with `ERR_GREEN_ROOM_FULL` when the resulting overlap count would reach 4; stated at the boundary, exactly four simultaneously overlapping bookings are legal, and the fifth overlapping request is the one rejected. A booking is born `BOOKED`; the owning contestant may cancel it, moving it to the terminal `CANCELLED` state, and a contest-level cancellation cascade cancels every `BOOKED` booking of the contest as described in §2.9.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, trigger a state transition, or perform a read return `200 OK`. All endpoints are mounted under the API's root prefix. List-endpoint filters are exact-match and combine conjunctively. A request to an undefined route, or an unsupported method on a defined route, is rejected with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/contest-events` | Create a contest (starts in `SETUP`) | ContestLead |
| GET | `/contest-events/{id}` | Read one contest including computed budget fields | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |
| POST | `/contest-events/{id}/transition` | Advance or revert contest status per the ContestEvent state machine | ContestLead |
| GET | `/contest-events/{id}/tax-summary` | Computed tax summary for the contest | Treasurer, ContestLead |
| GET | `/contest-events/{id}/categories` | List categories of a contest | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |
| GET | `/contest-events/{id}/judges` | List judges of a contest | ContestLead, Judge |
| POST | `/categories` | Create a category in a contest (starts `DRAFT`) | ContestLead |
| GET | `/categories/{id}` | Read one category | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |
| PATCH | `/categories/{id}` | Edit category configuration (OCC-guarded, `SETUP` only) | ContestLead |
| POST | `/categories/{id}/tabulate` | Compute final scores, assign ranks, tabulate the category | ContestLead |
| POST | `/categories/{id}/lock-scoresheets` | Bulk-lock all `SUBMITTED` scoresheets of the category | ContestLead |
| POST | `/contestants` | Self-register a contestant profile | Any authenticated role (the only endpoint open to `Anonymous`) |
| GET | `/contestants/{id}` | Read a contestant (self or lead) | Contestant, ContestLead |
| POST | `/contestants/{id}/consents` | Grant or revoke one media-consent scope | Contestant |
| GET | `/contestants/{id}/judges` | List judges linked to this contestant | ContestLead |
| POST | `/judges` | Onboard a judge to a contest panel | ContestLead |
| POST | `/entries` | Register an entry (starts `SUBMITTED`) | Contestant |
| GET | `/entries` | List entries with optional `category_id`, `contestant_id`, `contest_id`, `status` filters | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |
| GET | `/entries/{id}` | Read one entry | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |
| PATCH | `/entries/{id}` | Edit entry title/props (OCC-guarded; prop change on `SAFETY_REJECTED` resubmits) | Contestant |
| POST | `/entries/{id}/withdraw` | Withdraw an entry, releasing slots and compacting the stage queue | Contestant |
| POST | `/entries/{id}/disqualify` | Disqualify an entry with full cascade | ContestLead |
| POST | `/entries/{id}/safety-check` | Record a prop/weapon safety verdict (supports re-inspection) | SafetyOfficer |
| POST | `/prejudging-slots` | Define a craftsmanship-review slot for a category panel | ContestLead |
| GET | `/prejudging-slots` | List slots with optional `category_id`, `booked_entry_id`, `status` filters | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |
| GET | `/prejudging-slots/{id}` | Read one slot | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |
| POST | `/prejudging-slots/{id}/book` | Book an `OPEN` slot for an own `SAFETY_APPROVED` entry | Contestant |
| POST | `/prejudging-slots/{id}/release` | Release a `BOOKED` slot (owner or lead no-show) | Contestant, ContestLead |
| POST | `/prejudging-slots/{id}/complete` | Mark craftsmanship review done; booked entry becomes `PREJUDGED` | ContestLead |
| POST | `/scoresheets` | Create a rubric scoresheet for an entry and phase | Judge |
| GET | `/scoresheets` | List scoresheets with optional `entry_id`, `judge_id`, `category_id`, `status` filters | ContestLead, Judge |
| GET | `/scoresheets/{id}` | Read one scoresheet | ContestLead, Judge |
| POST | `/scoresheets/{id}/submit` | Submit own `DRAFT` sheet | Judge |
| POST | `/scoresheets/{id}/reopen` | Reopen a `LOCKED` sheet for correction (may cascade tabulation reopen) | ContestLead |
| POST | `/performance-slots` | Queue an entry onto the stage order with tech cues | StageManager |
| GET | `/performance-slots` | List stage slots with optional `contest_id`, `entry_id`, `status` filters | ContestLead, StageManager, Judge, Contestant |
| GET | `/performance-slots/{id}` | Read one stage slot | ContestLead, StageManager, Judge, Contestant |
| PATCH | `/performance-slots/{id}` | Update sequence, duration, or tech cues while `QUEUED` | StageManager |
| POST | `/performance-slots/{id}/advance` | Advance the stage walk (`QUEUED` → `ON_STAGE` → `COMPLETED`, or to `SKIPPED`) | StageManager |
| POST | `/prize-awards` | Create an award for a category rank | Treasurer |
| GET | `/prize-awards` | List awards with optional `category_id`, `entry_id`, `contest_id`, `status` filters | Treasurer, ContestLead |
| GET | `/prize-awards/{id}` | Read one award | Treasurer, ContestLead |
| POST | `/prize-awards/{id}/approve` | Checker approval (creator may not approve) | Treasurer |
| POST | `/prize-awards/{id}/disburse` | Pay the award, computing withholding variant | Treasurer |
| POST | `/prize-awards/{id}/mark-tax-reported` | Mark the 1099 as filed | Treasurer |
| POST | `/prize-awards/{id}/revoke` | Revoke a `PENDING` or `APPROVED` award, restoring budget | ContestLead |
| POST | `/green-room-bookings` | Book green-room time | Contestant |
| GET | `/green-room-bookings` | List bookings with optional `contestant_id`, `contest_id`, `room_name`, `status` filters | Contestant, ContestLead |
| GET | `/green-room-bookings/{id}` | Read one booking | Contestant, ContestLead |
| POST | `/green-room-bookings/{id}/cancel` | Cancel own booking | Contestant |
| POST | `/_clock/set_current_utc` | Advance the test-driving logical clock | ContestLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REGISTRATION_NOT_OPEN` | 409 |
| `ERR_PROP_BANNED` | 422 |
| `ERR_SAFETY_NOT_APPROVED` | 409 |
| `ERR_CONSENT_REQUIRED` | 409 |
| `ERR_JUDGE_CONFLICT` | 409 |
| `ERR_DUPLICATE_SCORESHEET` | 409 |
| `ERR_DUPLICATE_ENTRY` | 409 |
| `ERR_ENTRY_CATEGORY_MISMATCH` | 409 |
| `ERR_CATEGORY_FULL` | 409 |
| `ERR_DIVISION_AGE_INELIGIBLE` | 422 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_SEQUENCE_CONFLICT` | 409 |
| `ERR_SLOT_OUTSIDE_WINDOW` | 422 |
| `ERR_BOOKING_IN_PAST` | 422 |
| `ERR_GREEN_ROOM_INACCESSIBLE` | 422 |
| `ERR_GREEN_ROOM_FULL` | 409 |
| `ERR_PRIZE_BUDGET_EXCEEDED` | 422 |
| `ERR_TAX_FORM_REQUIRED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SCORESHEETS_NOT_LOCKED` | 409 |
| `ERR_CATEGORY_NOT_TABULATED` | 409 |
| `ERR_PLACEMENT_NOT_FOUND` | 409 |
| `ERR_NO_ELIGIBLE_ENTRIES` | 409 |
| `ERR_STALE_VERSION` | 412 |
