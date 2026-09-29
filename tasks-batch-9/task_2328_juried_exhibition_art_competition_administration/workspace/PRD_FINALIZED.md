# Juried Exhibition Administration API — Product Requirements Document

## 1. Introduction

An arts council that runs a juried exhibition is running four businesses at once. It is running a call for entries, with eligibility rules, media restrictions, size limits and a tiered fee schedule. It is running a jury — credentialled outside experts who must be booked, paid a prorated honorarium, screened for conflicts of interest, and kept blind to the identity of the artists they score. It is running a gallery, where physical objects arrive, are condition-reported, insured, hung on finite wall space, and eventually come back down. And it is running a small financial institution, where prizes are committed against a budget, sponsor money is ring-fenced, sales are split between tax, commission and artist payment, and every cent must reconcile before the books close.

Today most councils do this with spreadsheets, and the failures are predictable: an artist is accepted whose entry fee never cleared; a juror scores work by their own student; two works are planned onto the same 40 centimetres of wall; a purchase award is confirmed twice against the same sponsor budget; an artist is paid out with no tax form on file. This API exists to make each of those failures a rejected request with a specific, machine-readable reason rather than a discovery made after the opening reception.

The system is therefore designed around a small number of hard commitments. Every artwork carries two independent lifecycles — one for its jury and logistics fate, one for its physical placement — because a work can be accepted but unhung, or hung but unsold. Every exhibition likewise carries two independent lifecycles, one for the show and one for the money, because reconciliation continues after the doors close. Money is computed in whole cents with a pinned evaluation order, never re-derived from a rounded intermediate. Contested resources — a wall segment, an exhibition ledger, a jury round's session grid — are guarded by explicit version checks so that a decision is never taken against a picture of the world that has already moved on. And the duties that most invite abuse are split: whoever proposes a prize may not confirm it, and whoever records a sale may not release its artist payment.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold across every endpoint: authentication, response shape, pagination, resource identity, temporal semantics, monetary precision, concurrency control, and the fixed order in which validations are applied. Domain behaviour is specified in §3.

### 2.1. Council Roles and Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they are acting. If either header is absent, or if the supplied role is not one of the six roles the system recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The six roles are `CallManager`, `JuryChair`, `Juror`, `Artist`, `Registrar`, and `FinanceOfficer`. Every endpoint declares which of these roles may invoke it (see the table in §4); a request whose role is syntactically valid but not listed for the endpoint is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

Two of the six roles are **entity-backed**, meaning the header value is a foreign key into the data model rather than a bare operator label:

- When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting `Artist`; ownership checks on any resource that references an `Artist` compare the resource's foreign-key field to `X-User-ID`. Concretely, the acting artist must equal the `artist_id` of the entry being opened, submitted, paid for or withdrawn, and must equal the `artist_id` of the entry that owns an artwork whose images are being uploaded. An artist may only read and patch their own artist record.
- When `X-User-Role` is `Juror`, `X-User-ID` is the `id` of the acting `Juror`; ownership checks compare the target juror record's `id` to `X-User-ID`. A juror may confirm, resign or declare conflicts only on their own record, and when a juror submits a score the `juror_id` stored on that score is taken from `X-User-ID` and never from the request body.

The other four roles are opaque. When `X-User-Role` is `CallManager`, `JuryChair`, `Registrar`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — as `proposed_by_user_id` and `confirmed_by_user_id` on an `Award` for a `JuryChair`, as `reported_by_user_id` on a `ConditionReport` for a `Registrar`, and as `recorded_by_user_id` and `payout_released_by_user_id` on a `Sale` for a `FinanceOfficer` — but it does not compare it to any entity's `id`.

An ownership violation by an entity-backed actor is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The ownership check applies to opening an entry, attaching an artwork to an entry, submitting an entry, paying an entry fee, withdrawing an entry, uploading an artwork image, confirming a juror invitation, resigning as a juror, filing a juror conflict declaration, and patching an artist record.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, may not be lower than 1, and may not exceed 100. The `offset` parameter is the number of records to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, each collection endpoint accepts its own filters, which are the system's reverse-lookup mechanism in place of nested ownership URLs. Exhibitions may be filtered by `status` and `season_year`. Entries may be filtered by `exhibition_id`, `artist_id`, and `status`. Artworks may be filtered by `entry_id`, `exhibition_id` (resolved through the artwork's entry, since the artwork itself does not carry the exhibition key), `wall_segment_id`, `status`, and `placement_status`. Jury rounds accept `exhibition_id` and `status`; juror assignments accept `juror_id`, `jury_round_id`, and `status`; scores accept `jury_round_id`, `artwork_id`, and `juror_id`. Wall segments accept `exhibition_id`. Sponsors accept `exhibition_id` and `recognition_tier`. Awards accept `exhibition_id`, `artwork_id`, `sponsor_id`, and `status`. Sales accept `artwork_id`, `source_award_id`, and `status`. Condition-report listings accept `stage`.

### 2.4. Common Resource Properties

Most resources in this system are mutable, versioned records and carry a standard set of server-managed properties:

- **`id` (string)** — a server-minted UUID. It carries no type prefix.
- **`created_at` (string)** — an ISO 8601 UTC timestamp with three fractional digits, stamped when the record is first persisted.
- **`updated_at` (string)** — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the record, including mutations that only change a derived aggregate such as a count or a money total.
- **`version` (integer)** — a counter that begins at 1 on creation and increments by exactly 1 on every mutation of that record. It is the value clients quote back in the optimistic-concurrency fields described in §2.7. A field write mutates a record only when it actually moves the stored value, so an update that restates what the record already holds — a `PATCH` naming the `member_status` an artist already carries, or an honorarium remittance that leaves `honorarium_paid_cents` where it was — succeeds but leaves that record's `version` and `updated_at` untouched. Conversely, however many of one record's fields a single request rewrites, and however many cascades reach the same record, that request advances that record's `version` by at most 1; a record the request itself creates stays at `version` 1. None of this relaxes the version advances that §2.7 and §3 state for a contested parent: booking a session advances its round even though none of the round's own stored fields change.

Four record types are append-only evidence rather than living records, and they therefore carry only `id` and `created_at`: `ArtworkImage`, `ConflictDeclaration`, `Score`, and `ConditionReport`. For those four, both `updated_at` and `version` are absent from the resource entirely. Note that a `Score` is nonetheless subject to one server-side revision — its `voided_by_conflict` flag may be flipped — and that revision does not introduce a `version` or an `updated_at`.

Timestamps supplied by clients (window boundaries, session boundaries, capture dates) are ISO 8601 UTC instants and are stored as given. The four instants the server stamps or derives for itself — an `Entry`'s `submitted_at`, a `Score`'s `submitted_at`, an `Artwork`'s `claim_deadline_at`, and the `swept_at` an unclaimed sweep reports — are rendered in the same ISO 8601 UTC form with three fractional digits as `created_at`, even when the value they were computed from carried no fractional digits: a `claim_deadline_at` derived from a `closing_at` of `2026-11-01T18:00:00Z` therefore reads `2026-12-01T18:00:00.000Z`.

### 2.5. Identifier Resolution and Exhibition Scope Coherence

The URL topology is flat: every entity is addressed as a top-level collection, and relationships are carried by identifier fields rather than by nesting. Where a path does contain more than one identifier, the identifiers are resolved strictly left to right, and the first one that fails to resolve determines the 404 that is returned. A request naming an artwork under a non-existent path prefix therefore fails on the prefix, not on the artwork. Each entity type has its own not-found code: `ERR_EXHIBITION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_ARTWORK_NOT_FOUND`, `ERR_JUROR_NOT_FOUND`, `ERR_JURY_ROUND_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WALL_SEGMENT_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, and `ERR_SCORE_NOT_FOUND`, each returning HTTP 404. The same codes are used when an identifier supplied in a request body — `exhibition_id`, `artist_id`, `artwork_id`, `juror_id`, `wall_segment_id`, `sponsor_id`, `jury_round_id`, `entry_id` — does not resolve.

Because ownership is not expressed in the URL, coherence between aggregates is a business rule the server must enforce rather than a structural guarantee. Four such checks exist, and all four report `ERR_EXHIBITION_SCOPE_MISMATCH` (HTTP 422): the wall segment named in an installation plan must belong to the same exhibition as the artwork being planned; the artwork named in a score must belong to the exhibition that owns the jury round; the artwork named on an award must belong to the award's exhibition; and a sponsor attached to an award must belong to that same exhibition. The check is applied when an installation plan is filed, when a score is submitted, when an award is proposed, and again when an award is confirmed.

### 2.6. The Logical Clock and the Calendar of a Call

Every deadline, window and accrual in this system is evaluated against a server-side **logical clock**, never against wall-clock time. Before any call is made the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. Any role may move it by supplying a `to_iso8601` instant to the clock-setting endpoint, which answers with the resulting `current_utc`. Every subsequent window test, deadline test and storage accrual uses the instant the clock currently holds.

Window inclusivity is deliberate and differs between windows, so it is stated once here and relied on throughout §3:

- The submission window `[call_opens_at, call_closes_at)` is **half-open**. A submission-side operation at an instant strictly before `call_closes_at` is accepted; one at exactly `call_closes_at`, or later, is rejected with `ERR_CALL_WINDOW_CLOSED`. Conversely, jurying may not begin until the clock has reached `call_closes_at` — an attempt before that instant is rejected with `ERR_CALL_WINDOW_NOT_CLOSED`.
- The delivery window `[delivery_window_start_at, delivery_window_end_at]` is **closed** at both ends: an intake report at exactly either boundary is accepted. Outside it, `ERR_DELIVERY_WINDOW_INVALID`.
- A jury round's scoring window `[opens_at, closes_at]` is **closed** at both ends; a score outside it is rejected with `ERR_SCORING_WINDOW_CLOSED`.
- A juror session occupies the **half-open** interval `[session_start_at, session_end_at)`, so two sessions that merely touch at an endpoint do not overlap and both may be booked.
- The public phases are gated by lower bounds only: the show may not go on view before `opening_at` and may not close before `closing_at`, and a premature request is rejected with `ERR_PHASE_TIME_NOT_REACHED`. `notification_at` and `call_opens_at` are recorded for publication purposes and are not enforced as gates.

### 2.7. Optimistic Concurrency on Contested Parents

Six operations decide something against a shared parent record whose figures another writer may legitimately have changed: wall occupancy, exhibition capacity, the award budget, the settlement ledger, and a round's session grid. Each of those operations therefore requires the client to quote the parent's `version` as a mandatory, non-optional field in the request body, read from the parent's own read endpoint. If the quoted value does not equal the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written.

- Reserving a wall span for an artwork requires `expected_wall_segment_version`, matching the current `version` of the `WallSegment` named in the request. Another planner may have reserved centimetres on that wall since the acting registrar last read it — a non-colliding span always succeeds — so a stale quote means the planner's picture of `occupied_cm`, `available_cm` and `loaded_weight_kg` no longer describes the wall.
- Confirming an award requires `expected_exhibition_version`, matching the `Exhibition`'s current `version`. Confirming a different award legitimately consumes part of `award_budget_cents`, so a stale quote means the budget check would be computed against an out-of-date `award_committed_cents`.
- Promoting a waitlisted artwork requires `expected_exhibition_version`. Promoting a different waitlisted work legitimately raises `accepted_count`, so a stale quote means the promoter is deciding against a capacity figure the exhibition no longer has.
- Releasing an artist payout requires `expected_exhibition_version`. Releasing the payout of a different sale legitimately raises `payouts_released_cents`, so a stale quote means the releasing officer's view of the settlement ledger is out of date.
- Booking a juror session requires `expected_jury_round_version`, matching the `JuryRound`'s current `version`. Booking a different juror or a non-overlapping session legitimately succeeds and advances the round, so a stale quote means the chair is scheduling against a session grid that has already changed.
- Running the acceptance list requires `expected_exhibition_version`, matching the `Exhibition`'s current `version`, because the run rewrites the status of every shortlisted work and the exhibition's own counts.

No other endpoint accepts a version field. Where an endpoint is not named above, it performs no concurrency check and no `expected_…_version` input is defined for it.

### 2.8. Cents, Rounding and the Order of Arithmetic

Every monetary quantity in the system is an integer count of cents. There are no fractional cents anywhere in a stored field or a response body. Percentage configuration values (`member_discount_pct`, `commission_pct`, `sales_tax_pct`) and score weights (`score_weight_technique`, `score_weight_originality`, `score_weight_relevance`) are fractional numbers and retain the precision they were supplied with.

Where a monetary result must be rounded, the method is **round half up** — a value exactly halfway between two whole cents rounds away from zero. Where a monetary result must be truncated, the specification says so explicitly and means round toward negative infinity. Two derived score fields are rounded to **two decimal places**, again round half up: `composite_score`, and the two round means `provisional_mean_score` and `certified_mean_score`.

The order in which rounding is applied is part of each formula's contract, not an implementation detail, because different orders produce different cents from the same inputs. Two orders are pinned explicitly and must not be substituted for one another. In the entry fee, each fee **line** is rounded to whole cents before it is multiplied by a count and summed; rounding the discounted total once instead produces a fee one or two cents lower and is wrong. In the insurance premium, the insured total is converted to whole thousand-dollar units by rounding up **once on the aggregate**, never once per artwork. Section 3 states each formula step by step in the order it must be evaluated.

### 2.9. Segregation of Duties

Two decisions in this system may not be taken by the same operator who set them up, and the constraint is enforced on the opaque `X-User-ID` rather than on the role. The `X-User-ID` confirming an award must differ from the `proposed_by_user_id` recorded when the award was proposed, and the `X-User-ID` releasing an artist payout must differ from the `recorded_by_user_id` recorded when the sale was booked. Both violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Because both roles involved (`JuryChair` and `FinanceOfficer`) are opaque, a council staffed by a single chair or a single officer simply cannot complete those two operations — that is the intended consequence.

A related but distinct safeguard governs the jury: a juror who has declared a conflict of interest with an artist may not score that artist's work, and the attempt is rejected with `ERR_JUROR_CONFLICT_DECLARED` (HTTP 403). Declarations also act retroactively on scores already cast; see §3.4.

### 2.10. Order of Validation

When several checks could reject the same request, the server applies them in a fixed order and returns the error of the **first** check that fails. This ordering is normative: it is what makes an error code predictable when a request is wrong in more than one way. The ladder, from highest precedence to lowest, is:

1. **Header authentication** — both auth headers present and the role recognised, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Role permission** — the acting role is listed for the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.
3. **Path identifier existence** — every identifier in the path resolves, left to right, else the corresponding 404 code from §2.5. Applies to every endpoint with a path identifier.
4. **Body foreign-key existence** — every identifier supplied in the body resolves, else the corresponding 404 code. Applies to opening an entry, creating a jury round, booking an assignment, submitting a score, registering a wall segment, registering a sponsor, proposing an award, recording a sale, filing an installation plan, and filing a conflict declaration.
5. **Ownership** — the entity-backed ownership check of §2.1, else `ERR_NOT_RESOURCE_OWNER` (403), over the ten operations enumerated there.
6. **Body schema** — required fields present, enum members drawn from the declared sets, integers within range (each score criterion from 1 to 10 inclusive, `photo_count` at least 1, cent amounts non-negative), `span_start_cm` strictly less than `span_end_cm`, the three score weights summing to exactly 1.00, `damage_notes` present when `condition_grade` is `DAMAGED`, `list_price_cents` present when `for_sale` is true, and both `carrier` and `tracking_number` present when `return_method` is `COURIER`. Any violation is `ERR_INVALID_REQUEST` (400). Applies to every write endpoint.
7. **Target state** — the target record is in a state from which the requested transition is declared, else the state code for that record type: `ERR_ENTRY_STATE_INVALID`, `ERR_ARTWORK_STATE_INVALID`, `ERR_JURY_ROUND_STATE_INVALID`, `ERR_AWARD_STATE_INVALID`, `ERR_SALE_STATE_INVALID`, or `ERR_ASSIGNMENT_STATE_INVALID`, all HTTP 409. Applies to every action endpoint.
8. **Exhibition phase guard** — the exhibition's `status` permits the operation and the requested target phase is reachable from it, else `ERR_EXHIBITION_PHASE_INVALID` (409). Applies to phase advance, the acceptance-list run, every entry operation, driving a jury round's status, waitlist promotion, filing a condition report, filing an installation plan, marking a work installed, confirming an award, recording a sale, and advancing settlement.
9. **Settlement phase guard** — the exhibition's `settlement_status` permits the operation and the requested target settlement phase is reachable from it, else `ERR_SETTLEMENT_PHASE_INVALID` (409). Applies to advancing settlement, releasing a payout, voiding a sale, and rescinding an award.
10. **Juror engagement** — the juror is `CONFIRMED`, else `ERR_JUROR_NOT_CONFIRMED` (409). Applies to booking an assignment and submitting a score.
11. **Reopen budget** — a completed round may be reopened only while `reopen_count` is below 2, else `ERR_ROUND_REOPEN_LIMIT` (409).
12. **Cross-exhibition coherence** — the four checks of §2.5, else `ERR_EXHIBITION_SCOPE_MISMATCH` (422).
13. **Saleability** — a gallery sale requires the work to be `for_sale` with a `list_price_cents`, else `ERR_ARTWORK_NOT_FOR_SALE` (422).
14. **Juror conflict** — the acting juror has declared no conflict naming the artwork's artist, else `ERR_JUROR_CONFLICT_DECLARED` (403). Applies to score submission.
15. **Segregation of duties** — the two checks of §2.9, else `ERR_SEGREGATION_OF_DUTIES` (403). Applies to award confirmation and payout release.
16. **Condition-report prerequisite** — the required report exists, else `ERR_CONDITION_REPORT_REQUIRED` (409). Applies to deinstallation and to arranging a return shipment.
17. **Condition block** — the work's `intake_condition_grade` is not `DAMAGED` before a wall span may be reserved, else `ERR_ARTWORK_CONDITION_BLOCKED` (422).
18. **Insurance ceiling** — `declared_value_cents` is at most `per_work_insurance_cap_cents`, else `ERR_INSURANCE_COVERAGE_MISSING` (409). Applies to the installation plan.
19. **Tax form** — the artist has `tax_form_on_file` true, else `ERR_TAX_FORM_MISSING` (422). Applies to payout release.
20. **Payout hold** — the artist's `payout_hold` is false, else `ERR_ARTIST_PAYOUT_HOLD` (409). Applies to payout release.
21. **Call window open** — the clock is strictly before `call_closes_at`, else `ERR_CALL_WINDOW_CLOSED` (409). Applies to opening an entry, attaching an artwork, submitting an entry, paying a fee, and opening the call for entries.
22. **Call window closed** — the clock has reached `call_closes_at`, else `ERR_CALL_WINDOW_NOT_CLOSED` (409). Applies to advancing to jurying.
23. **Scoring window** — the clock lies within the round's closed window, else `ERR_SCORING_WINDOW_CLOSED` (409).
24. **Session containment** — the requested session lies inside the round's closed window, else `ERR_SESSION_OUTSIDE_ROUND_WINDOW` (422).
25. **Session overlap** — the juror holds no other `BOOKED` or `COMPLETED` assignment whose half-open interval intersects the requested one, else `ERR_JUROR_SESSION_OVERLAP` (409).
26. **Delivery window** — an intake report lies inside the closed delivery window, and entry into the installation phase happens no later than `delivery_window_end_at`, else `ERR_DELIVERY_WINDOW_INVALID` (409).
27. **Phase time reached** — the clock has reached `opening_at` for going on view, and `closing_at` for closing, else `ERR_PHASE_TIME_NOT_REACHED` (409).
28. **Residency eligibility** — the artist's `residency_state_code` appears in the exhibition's `eligible_state_codes`, else `ERR_ELIGIBILITY_NOT_MET` (422). Applies to opening an entry and to submitting it.
29. **Media category** — the artwork's `medium_category` appears in `allowed_media_categories`, else `ERR_MEDIA_CATEGORY_NOT_ALLOWED` (422). Applies to attaching an artwork.
30. **Size limits** — `longest_edge_cm` is at most `max_dimension_cm` and `weight_kg` is at most the exhibition's `max_weight_kg`, else `ERR_SIZE_LIMIT_EXCEEDED` (422). Applies to attaching an artwork.
31. **Works per entry** — attaching the work would not push `works_count` past `max_works_per_entry`, else `ERR_MAX_WORKS_EXCEEDED` (422).
32. **Entries per artist** — the artist's entries in this exhibition whose `status` is `DRAFT`, `PENDING_FEE` or `SUBMITTED` would not exceed `max_entries_per_artist`, else `ERR_ENTRY_LIMIT_EXCEEDED` (409). Applies to opening an entry.
33. **Image standard** — `ERR_IMAGE_STANDARD_VIOLATION` (422); see §3.2 for the five criteria.
34. **Image metadata** — `ERR_IMAGE_METADATA_INCOMPLETE` (422); see §3.2.
35. **Primary image** — `ERR_PRIMARY_IMAGE_REQUIRED` (409). Applies to submitting an entry, waiving its fee, and uploading an image that would be a second `PRIMARY` for the same work.
36. **Round number uniqueness** — `round_number` is unused within the exhibition, else `ERR_DUPLICATE_ROUND_NUMBER` (409).
37. **One score per juror per work per round** — else `ERR_DUPLICATE_SCORE` (409).
38. **Quorum** — the round's `quorum_shortfall_count` is 0 before it may complete, else `ERR_QUORUM_NOT_MET` (409).
39. **Non-empty candidate set** — the acceptance-list candidate set is non-empty, else `ERR_NO_ELIGIBLE_ARTWORKS` (409).
40. **Acceptance capacity** — `accepted_count` is strictly below `acceptance_capacity` before a promotion, else `ERR_ACCEPTANCE_CAPACITY_REACHED` (409).
41. **Span bounds** — `span_start_cm` is at least 0, strictly less than `span_end_cm`, and `span_end_cm` is at most the wall's `length_cm`, else `ERR_WALL_SPAN_OUT_OF_BOUNDS` (422).
42. **Span buffer collision** — else `ERR_WALL_SPAN_CONFLICT` (409); see §3.7 for the buffer rule.
43. **Wall load** — the wall's `loaded_weight_kg` plus the work's `weight_kg` is at most the wall's `max_weight_kg`, else `ERR_WALL_WEIGHT_EXCEEDED` (422).
44. **Installation completeness** — every `ACCEPTED` or `DELIVERED` work has `placement_status` `INSTALLED` before the show goes on view, else `ERR_INSTALLATION_INCOMPLETE` (409).
45. **Wall inventory** — at least one wall segment exists for the exhibition before the installation phase, else `ERR_WALL_SEGMENT_REQUIRED` (409).
46. **Fee amount** — the tendered `amount_cents` equals the frozen `entry_fee_cents` exactly, else `ERR_FEE_AMOUNT_MISMATCH` (402).
47. **Council award budget** — else `ERR_AWARD_BUDGET_EXCEEDED` (402); see §3.8.
48. **Sponsor purchase budget** — else `ERR_SPONSOR_BUDGET_EXCEEDED` (402); see §3.8.
49. **Buyer payment amount** — the tendered `amount_cents` equals `buyer_total_cents` exactly, else `ERR_PAYMENT_AMOUNT_MISMATCH` (402).
50. **Concurrency** — the `expected_…_version` field equals the parent's current `version`, else `ERR_STALE_VERSION` (412), over the six operations of §2.7.

The practical consequence is worth stating plainly with an example. When a juror who has declared a conflict submits a duplicate score outside the round's scoring window, three checks would all reject the request; the conflict check sits at position 14, the window check at 23 and duplicate detection at 37, so the response is `ERR_JUROR_CONFLICT_DECLARED`. Precedence is decided by the positions above and not by intuition about which fault is graver.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Call for Entries

A `CallManager` opens the season by creating an **Exhibition**, which is simultaneously the call for entries, the jury's docket, the gallery's floor plan and the season's ledger. Creation captures the `title` printed on the call and the `season_year`, which is also the prefix of every anonymous jury label the exhibition will mint. The published calendar is supplied in full at creation: `call_opens_at` and `call_closes_at` bracket submissions, `notification_at` is the date on which results are announced, `delivery_window_start_at` and `delivery_window_end_at` bracket physical delivery, and `opening_at` and `closing_at` bracket the public run. `claim_deadline_days` — 30 unless overridden — sets how long after closing an artist has to collect unsold work.

The fee schedule is configured alongside the calendar. `entry_fee_base_cents` covers the first `works_included_in_base` works (2 unless overridden), `entry_fee_additional_cents` prices each work beyond that, and `member_discount_pct` — 0.175 unless overridden — is the fractional discount council members receive on those two lines. Submission volume is bounded by `max_works_per_entry` (5 unless overridden) and `max_entries_per_artist` (1 unless overridden). Physical admissibility is bounded by `max_dimension_cm` and `max_weight_kg`, and insurance exposure by `per_work_insurance_cap_cents`. Eligibility is expressed as two whitelists: `allowed_media_categories`, a non-empty subset of `PAINTING`, `SCULPTURE`, `PHOTOGRAPHY`, `PRINTMAKING`, `TEXTILE` and `NEW_MEDIA`; and `eligible_state_codes`, a non-empty list of two-letter residency codes.

Jury and selection policy is also fixed up front. `jury_quorum` is the default quorum copied onto each round that does not name its own. `advance_score_threshold` is the inclusive bar a work's certified mean must reach to be shortlisted. The three criterion weights `score_weight_technique`, `score_weight_originality` and `score_weight_relevance` must sum to exactly 1.00. Selection volume is bounded by `acceptance_capacity` and `waitlist_capacity`. Finally the money policy: `commission_pct` is the council's share of a gallery sale's taxable base, `sales_tax_pct` is the tax rate, and `award_budget_cents` is the council's own cash prize budget.

A new exhibition begins with `status` at `DRAFT` and `settlement_status` at `NOT_STARTED`, every computed count and money aggregate at zero, and `version` at 1. The two axes then advance independently of one another, and the `status` axis is driven by the `CallManager` naming a `target_status`. The permitted advances along that axis are `DRAFT → OPEN_FOR_ENTRIES`, `OPEN_FOR_ENTRIES → JURYING`, `RESULTS_PUBLISHED → INSTALLATION`, `INSTALLATION → ON_VIEW`, and `ON_VIEW → CLOSED`. `RESULTS_PUBLISHED` is deliberately **not** reachable by naming it as a target: the only way into it is the acceptance-list run of §3.6. Any target that is not reachable from the current phase, and any operation attempted in a phase that does not permit it, yields `ERR_EXHIBITION_PHASE_INVALID`. Every successful advance increments the exhibition's `version` by 1 and refreshes its `updated_at`.

Opening the call requires more than being in `DRAFT`. The three score weights must already sum to exactly 1.00, both `allowed_media_categories` and `eligible_state_codes` must be non-empty, and the clock must still be strictly before `call_closes_at` — opening a call whose deadline has already passed is refused with `ERR_CALL_WINDOW_CLOSED`. Moving on to `JURYING` is the mirror image: it is refused with `ERR_CALL_WINDOW_NOT_CLOSED` until the clock has reached `call_closes_at`, because the docket must be final before jurors see it. That advance also performs the deadline sweep described in §3.3.

Gallery inventory is registered separately, by either a `CallManager` or a `Registrar`, as **WallSegment** records naming the `exhibition_id`, a gallery `label`, the usable hanging `length_cm`, an aggregate load limit `max_weight_kg`, and a `lighting_class` of `STANDARD` (the default) or `MUSEUM`. A freshly registered wall reports `occupied_cm` of 0 and `available_cm` equal to its `length_cm`, with `loaded_weight_kg` at 0.

### 3.2. Artists, Entries and the Works Attached to Them

The council's roster is maintained by the `CallManager`, who registers each **Artist** with a `legal_name` used on payment remittances, a unique `email`, and a two-letter `residency_state_code`. Three further attributes may be set at registration or later: `member_status`, either `MEMBER` or `NON_MEMBER` (the default), which decides the entry-fee discount; `tax_form_on_file`, false by default, which gates every payout; and `payout_method`, either `CHECK` (the default) or `ACH`. A newly registered artist has `payout_hold` false and `unclaimed_forfeit_count` at 0. Administrative updates to an artist record may be made by the artist themselves on their own record, or by a `CallManager`; only a `CallManager` may supply `payout_hold` to lift a hold the system has imposed.

An `Artist` opens an **Entry** against a call by naming the `exhibition_id` and their own `artist_id`. The entry is created in `DRAFT` with `entry_fee_cents` at 0 — nothing is assessed until submission. Two gates apply at this point: the artist's `residency_state_code` must appear in the call's `eligible_state_codes`, or the request is refused with `ERR_ELIGIBILITY_NOT_MET`; and the artist's existing entries in this exhibition whose `status` is `DRAFT`, `PENDING_FEE` or `SUBMITTED` must leave room under `max_entries_per_artist`, or the request is refused with `ERR_ENTRY_LIMIT_EXCEEDED`. Entries that have reached `WITHDRAWN` do not count against that limit.

Works are attached to a `DRAFT` entry one at a time. Each **Artwork** is described by its `title`, its `medium_category`, its framed `width_cm`, `height_cm` and `depth_cm`, its framed `weight_kg`, its `year_created`, and its `declared_value_cents` for insurance. If the work is offered for sale the artist sets `for_sale` to true — it is false by default — and must supply a `list_price_cents`, which is the posted, tax-inclusive price. From the three dimensions the server derives `longest_edge_cm` as the greatest of `width_cm`, `height_cm` and `depth_cm`. Three admissibility checks then run: the `medium_category` must be one of the call's `allowed_media_categories`, or `ERR_MEDIA_CATEGORY_NOT_ALLOWED`; `longest_edge_cm` must not exceed `max_dimension_cm` and `weight_kg` must not exceed the exhibition's `max_weight_kg`, or `ERR_SIZE_LIMIT_EXCEEDED`; and the entry's `works_count` — the number of its works whose `status` is anything other than `WITHDRAWN` — must stay within `max_works_per_entry`, or `ERR_MAX_WORKS_EXCEEDED`.

Each accepted work is created with `status` `DRAFT` on its jury-and-logistics axis and `placement_status` `UNPLACED` on its physical axis, with `wall_segment_id`, `span_start_cm` and `span_end_cm` all null, and with `storage_fee_cents` at 0. It is also assigned a `blind_label`, the anonymous identifier by which jurors will know it: the exhibition's `season_year`, a hyphen, and the one-based ordinal of this work among all of the exhibition's artworks ordered by `created_at` ascending, zero-padded to four digits. The first work registered against a 2026 season therefore carries the label `2026-0001`. Attaching a work refreshes the entry's `works_count`.

Digital submission standards are enforced on upload rather than at review time, so an artist learns immediately that a file is unusable. An **ArtworkImage** record names its `role` — exactly one `PRIMARY` image per work, plus any number of `DETAIL` images — its container `format`, its `pixel_long_edge` and `pixel_short_edge`, its `file_bytes`, its `color_profile`, a `capture_date`, a `credit_line` naming the photographer, and a `checksum_sha256` digest recorded for provenance. Five criteria constitute the digital standard, and any failure is refused with `ERR_IMAGE_STANDARD_VIOLATION`: the `format` must be `JPEG` or `PNG` (a `TIFF` is a valid enum member but does not meet the standard); `pixel_long_edge` must be at least 1200; `pixel_short_edge` must be at least 800; `file_bytes` must be at most 8,388,608, that is 8 mebibytes; and `color_profile` must be `SRGB`, not `ADOBE_RGB` and not `CMYK`. Two metadata criteria are checked separately and reported as `ERR_IMAGE_METADATA_INCOMPLETE`: `credit_line` must be non-empty, and `capture_date` must be present and must not fall after the current logical clock. Because a violating upload is refused rather than stored, every persisted image reports `standard_ok` as true. A successful upload refreshes the work's `primary_image_count`, the count of its images whose `role` is `PRIMARY`; an attempt to upload a second `PRIMARY` image for the same work is refused with `ERR_PRIMARY_IMAGE_REQUIRED`.

Reading an artwork is identity-aware. For a `Juror` reader, while any `BLIND_SCORING` round of that artwork's exhibition has `status` `OPEN`, the work's `entry_id` is returned as null and its `blind_label` is the only identifier available; during a `DELIBERATION` round, and for every other role at all times, `entry_id` is returned normally. Image listings and the exhibition's own record are unaffected by the mask.

### 3.3. Assessing the Fee, Submitting, Waiving and Withdrawing

Submission is a two-step handshake, which is what makes an unpaid entry visible rather than silently valid. An artist first submits the entry, advancing it `DRAFT → PENDING_FEE`, which freezes the assessed fee and stamps `submitted_at` with the logical clock. Submission requires that the exhibition be `OPEN_FOR_ENTRIES`, that the clock be strictly before `call_closes_at`, that `works_count` be at least 1, that every work of the entry have a `primary_image_count` of at least 1 — otherwise `ERR_PRIMARY_IMAGE_REQUIRED` — and that the artist's `residency_state_code` still appear in `eligible_state_codes`.

The **fee assessment** frozen at that moment is computed as follows, in this order. A discount fraction is taken: it is the exhibition's `member_discount_pct` when the artist's `member_status` is `MEMBER`, and zero otherwise. The base line is the exhibition's `entry_fee_base_cents` multiplied by one minus that discount fraction, rounded half up to whole cents. The number of additional works is the entry's `works_count` minus `works_included_in_base`, floored at zero. The additional line is the exhibition's `entry_fee_additional_cents` multiplied by one minus the discount fraction, rounded half up to whole cents. The oversize count is the number of the entry's works whose `status` is anything other than `WITHDRAWN` and whose `longest_edge_cm` is greater than 120.0 centimetres — that is, works with an edge longer than 1.2 metres. The frozen `entry_fee_cents` is then the base line, plus the number of additional works multiplied by the additional line, plus the oversize count multiplied by a flat handling surcharge of 2,000 cents per oversize work. Two properties of this order are load-bearing: each of the two discounted lines is rounded to whole cents *before* being multiplied and summed, so a 4,500-cent base and a 1,500-cent additional line at a 0.175 discount contribute 3,713 cents and 1,238 cents per additional work rather than a single rounding of the discounted total; and the oversize surcharge is never discounted, however the artist's membership stands.

With the fee frozen, the artist pays it by tendering an `amount_cents` that equals `entry_fee_cents` **exactly** — any other amount, over or under, is refused with `ERR_FEE_AMOUNT_MISMATCH`, and payment is only possible while the clock is still strictly before `call_closes_at`. A successful payment records `fee_paid_cents`, advances the entry `PENDING_FEE → SUBMITTED`, and cascades: every work of the entry whose `status` is `DRAFT` advances to `SUBMITTED`, each such work's own `version` incrementing by 1 alongside the entry's.

A `CallManager` may instead waive the fee under the council's hardship policy, from either `DRAFT` or `PENDING_FEE`, with identical effects in both cases — the waiver supersedes an unpaid assessment. A waiver sets `fee_waived` to true, sets `entry_fee_cents` to 0 and `fee_paid_cents` to 0, advances the entry to `SUBMITTED`, stamps `submitted_at`, and performs the same `DRAFT → SUBMITTED` cascade over the entry's works. A waiver requires the exhibition to be `OPEN_FOR_ENTRIES`, `works_count` to be at least 1, and every work to have at least one `PRIMARY` image.

Withdrawal is available to the owning artist and to a `CallManager` from `DRAFT`, `PENDING_FEE` or `SUBMITTED`, and only while the exhibition is `OPEN_FOR_ENTRIES` or `JURYING`. It is blocked once the entry has skin in the show: if any of its works holds `ACCEPTED`, `WAITLISTED`, `DELIVERED`, `ON_VIEW` or `SOLD`, the withdrawal is refused. A successful withdrawal moves the entry to `WITHDRAWN`, moves each of its works whose `status` is `DRAFT`, `SUBMITTED` or `SHORTLISTED` to `WITHDRAWN`, and recomputes the exhibition's `shortlisted_count`.

The deadline sweep that fires when the `CallManager` advances the exhibition `OPEN_FOR_ENTRIES → JURYING` is the same policy applied in bulk, and it cascades three hops. First, every entry of that exhibition whose `status` is `DRAFT` or `PENDING_FEE` moves to `WITHDRAWN` — an entry that never paid by the deadline does not reach the jury. Second, each entry entering `WITHDRAWN` drives its own works whose `status` is `DRAFT` or `SUBMITTED` to `WITHDRAWN`. Third, each work entering `WITHDRAWN` drives a recompute of its entry's `works_count` and of the exhibition's `insured_value_total_cents`.

Two derived counts on the entry make its jury standing legible without a query. `works_count` is the number of its works not `WITHDRAWN`; `shortlisted_count` is the number of its works whose `status` is any of `SHORTLISTED`, `ACCEPTED`, `WAITLISTED`, `DELIVERED`, `ON_VIEW`, `SOLD`, `RETURN_PENDING`, `RETURN_SCHEDULED`, `RETURNED` or `UNCLAIMED_FORFEIT` — that is, every state a work can only reach by having cleared the first round.

### 3.4. Convening the Jury: Invitations, Conflicts, Sessions and Honoraria

A `JuryChair` invites each **Juror** with a public `display_name`, a unique `email`, a non-empty `expertise_categories` list drawn from the same six media categories, and an `honorarium_cents` figure that is the total agreed fee for that juror across *all* of their sessions, not a per-session rate. A juror begins at `status` `INVITED` with `honorarium_committed_cents` and `honorarium_paid_cents` at 0. Accepting the invitation advances the juror `INVITED → CONFIRMED`, and may be performed either by the juror on their own record or by the chair on their behalf. Resignation, available from `INVITED` or `CONFIRMED` and likewise performable by either party, moves the juror to the terminal `RESIGNED`.

Conflicts of interest are declared as first-class records rather than as free-text notes. A **ConflictDeclaration** names the `juror_id` of the declaring juror, the `artist_id` they are conflicted with, and a `relation_type` of `FAMILY`, `TEACHER_STUDENT`, `SAME_GALLERY`, `COLLABORATOR` or `FINANCIAL_INTEREST`. Declarations are visible from both sides — a juror's own declarations, and a reverse lookup of every declaration naming a given artist. Filing a declaration acts **retroactively**: every existing score cast by that juror on any work belonging to that artist has its `voided_by_conflict` flag flipped to true, and the declaration reports how many it invalidated in `voided_score_count`. Voiding scores in turn forces a recompute of each affected artwork's `provisional_mean_score` and `valid_score_count`, and of each affected round's `quorum_shortfall_count` — a late declaration can therefore make a round that appeared complete no longer completable. Going forward, the same juror is refused with `ERR_JUROR_CONFLICT_DECLARED` on any attempt to score that artist's work. A juror's `conflict_count` reports how many declarations they have filed.

Sessions are booked as **JurorAssignment** records against a specific round: the chair names the `juror_id`, the `session_start_at` and `session_end_at` bounding the sitting, and the round's `expected_jury_round_version`. The juror must be `CONFIRMED`, or the booking is refused with `ERR_JUROR_NOT_CONFIRMED`. The session must lie entirely inside the round's `[opens_at, closes_at]` window, or `ERR_SESSION_OUTSIDE_ROUND_WINDOW`. And the session must not collide with the juror's existing commitments: if any other assignment of the same juror whose `status` is `BOOKED` or `COMPLETED` has a half-open interval intersecting the requested `[session_start_at, session_end_at)`, the booking is refused with `ERR_JUROR_SESSION_OVERLAP`. Because the intervals are half-open, a session ending at exactly the instant another begins does not collide, and back-to-back sittings are legal. A booked assignment starts at `status` `BOOKED` and reports `session_minutes`, the whole number of minutes between its start and end, and `scores_submitted_count`, the number of scores that juror has filed in that round.

The **honorarium proration** runs whenever a juror's set of active sessions changes — on a new booking, on a cancellation, and on the resignation cascade — and it exists to keep a juror's total pay exactly equal to their agreed `honorarium_cents` no matter how the sessions are sliced. The active set is all of that juror's assignments whose `status` is `BOOKED` or `COMPLETED`, taken across every round they sit on; if that set is empty, every share is 0. The total minutes is the sum of `session_minutes` over the active set. Each active assignment's `honorarium_share_cents` is then the juror's `honorarium_cents` multiplied by that assignment's `session_minutes`, divided by the total minutes, truncated downward to a whole cent. Because truncation loses cents, a remainder is computed as the juror's `honorarium_cents` minus the sum of the truncated shares, and that remainder is distributed one cent at a time to the active assignments taken in order of `created_at` ascending — never by identifier — until it is exhausted. A juror paid 50,000 cents across three equal 100-minute sessions therefore receives 16,667, 16,667 and 16,666 cents, summing to exactly 50,000. A `CANCELLED` assignment always carries a share of 0 and is excluded from the active set.

Cancelling a booked session is a `JuryChair` action and is refused with `ERR_JURY_ROUND_STATE_INVALID` once the round it serves has reached `CLOSED`. Cancellation moves the assignment `BOOKED → CANCELLED`, sets its `honorarium_share_cents` to 0, and cascades three hops: the proration re-runs over the juror's remaining `BOOKED` and `COMPLETED` assignments, the juror's `honorarium_committed_cents` is recomputed as the sum of shares over those assignments, and the exhibition's `jury_cost_committed_cents` is recomputed as the sum of `honorarium_share_cents` over all assignments whose `status` is `BOOKED` or `COMPLETED` and whose round belongs to that exhibition. A juror's `assignment_count` counts the same `BOOKED` and `COMPLETED` set, taken across every round they sit on; it is a field of the `Juror` record alone, and neither a `JuryRound` nor a `JurorAssignment` carries any assignment count of its own.

Resignation is the bulk form of the same cascade and runs five hops. Every assignment of the resigning juror whose `status` is `BOOKED` moves to `CANCELLED`; each cancellation re-runs the proration over the juror's remaining assignments; the juror's `honorarium_committed_cents` is recomputed; the `jury_cost_committed_cents` of every affected exhibition is recomputed; and the `quorum_shortfall_count` of every affected round is recomputed, which may leave a round uncompletable until other jurors fill the gap.

Honorarium money is remitted by a `FinanceOfficer`, who tenders an `amount_cents` that is added to the juror's `honorarium_paid_cents`, up to the juror's committed share.

### 3.5. Scoring: Composite Scores, Quorum Certification and Round Cycling

A `JuryChair` creates each **JuryRound** against an `exhibition_id` with a `round_number` — at least 1, and unique within that exhibition, else `ERR_DUPLICATE_ROUND_NUMBER` — and a `round_type` of either `BLIND_SCORING`, which masks artist identity from juror readers, or `DELIBERATION`, which reveals it. The round declares its scoring window with `opens_at` and `closes_at`, and may declare its own `quorum_required`; when that field is omitted it is copied from the exhibition's `jury_quorum`. A round begins at `status` `PENDING` with `reopen_count` at 0.

The round machine is cyclic. `PENDING → OPEN` requires the exhibition to be `JURYING` and requires at least one `BOOKED` assignment to exist for the round — a round with no jurors booked cannot open. `OPEN → SCORING_COMPLETE` requires the round's `quorum_shortfall_count` to be exactly 0, else `ERR_QUORUM_NOT_MET`. `SCORING_COMPLETE → OPEN` reopens the round for more scoring, and is permitted only while `reopen_count` is below 2 and the exhibition is still `JURYING`; a third reopen attempt is refused with `ERR_ROUND_REOPEN_LIMIT`. `SCORING_COMPLETE → CLOSED` finishes the round for good and cascades every assignment of that round whose `status` is `BOOKED` to `COMPLETED`, retaining each one's `honorarium_share_cents`. Any target that is not one of these four transitions from the round's present state is refused with `ERR_JURY_ROUND_STATE_INVALID`.

A `Juror` submits one **Score** per work per round, naming the `artwork_id` and the three criteria `technique`, `originality` and `relevance`, each an integer from 1 to 10 inclusive. The `juror_id` recorded on the score is the acting juror's identity from the request headers, never a body field, and `submitted_at` is stamped from the logical clock. Four gates apply beyond the standard ladder: the juror must be `CONFIRMED`; the clock must lie inside the round's closed `[opens_at, closes_at]` window, else `ERR_SCORING_WINDOW_CLOSED`; the scored work must belong to the round's exhibition, else `ERR_EXHIBITION_SCOPE_MISMATCH`; and no score may already exist for this combination of round, work and juror, else `ERR_DUPLICATE_SCORE`. A new score is created with `voided_by_conflict` false.

The **composite score** is computed on submission. The raw value is `technique` multiplied by the exhibition's `score_weight_technique`, plus `originality` multiplied by `score_weight_originality`, plus `relevance` multiplied by `score_weight_relevance`. The server then evaluates `expertise_match`, which is true when the artwork's `medium_category` appears in the acting juror's `expertise_categories` and false otherwise. When `expertise_match` is true the raw value is kept in full, so a perfect card of ten, ten and ten yields a `composite_score` of 10.00. When `expertise_match` is false the value is capped: the lesser of the raw value and 8.00 is taken, so the same perfect card from a juror outside their credentialled medium yields 8.00. Either way, exactly one rounding is applied — half up to two decimal places, after the cap, never before it.

Two round means are maintained per artwork, and they are deliberately different figures computed from the same evidence. Both begin by collecting that work's scores in that round whose `voided_by_conflict` is false — conflict-voided scores are excluded from both — and ordering them by `created_at` ascending, ties broken by `composite_score` ascending, never by identifier. The **provisional** figure, `provisional_mean_score`, is the arithmetic mean of `composite_score` over *every* score in that ordering, rounded half up to two decimal places, and it is refreshed on every submission while the round is `OPEN`; it is the live figure a chair watches, and a late high score raises it. The **certified** figure, `certified_mean_score`, is the arithmetic mean of `composite_score` over only the **first `quorum_required` elements** of that same ordering, rounded half up to two decimal places, and it is written once, at the moment the round completes. Only the certified figure decides anything. The divergence is real and intended: four valid scores of 7.15, 7.00, 6.00 and 10.00 in that order give a provisional mean of 7.54, while a `quorum_required` of 3 gives a certified mean of 6.72, which falls below a `advance_score_threshold` of 7.00 and declines the work. The work also reports `valid_score_count`, the number of its scores in the exhibition's round number 1 whose `voided_by_conflict` is false, and each round reports `scored_artwork_count`, the number of distinct works holding at least one non-voided score in it.

Quorum is the round's own gate on completion. `quorum_shortfall_count` is the number of the exhibition's works whose `status` is `SUBMITTED` and whose count of non-voided scores in that round is strictly below the round's `quorum_required`; the round may not complete until that number is zero.

Completing round number 1 is the fork that separates the shortlist from the rest. As the round moves `OPEN → SCORING_COMPLETE`, every work of that exhibition whose `status` is `SUBMITTED` has its `certified_mean_score` written by the certified variant above, and then forks on the inclusive threshold: a work whose `valid_score_count` has reached the round's `quorum_required` and whose `certified_mean_score` is greater than or equal to the exhibition's `advance_score_threshold` advances `SUBMITTED → SHORTLISTED`, while one whose certified mean falls strictly below the threshold moves `SUBMITTED → DECLINED`. Both branches increment the work's own `version`. The shortlist side additionally drives a recompute of the owning entry's `shortlisted_count` and of the exhibition's `shortlisted_count`, the count of that exhibition's works currently holding `SHORTLISTED`.

Reopening a completed round undoes that fork rather than layering on top of it. On `SCORING_COMPLETE → OPEN` the round's `reopen_count` increases by one, every work of the exhibition whose `status` is `SHORTLISTED` or `DECLINED` reverts to `SUBMITTED` with its `certified_mean_score` cleared to null, and the exhibition's `shortlisted_count` is recomputed. Scoring then resumes against the same round, and a subsequent completion re-derives the fork from whatever the evidence now is.

### 3.6. Determining the Acceptance List and Working the Waitlist

Publishing results is a single `JuryChair` operation that both computes the acceptance list and carries the exhibition `JURYING → RESULTS_PUBLISHED`. It requires the exhibition to be in `JURYING`, requires **every** jury round of that exhibition to have reached `CLOSED`, and requires the chair to quote `expected_exhibition_version`.

The run begins with an eligibility filter. The candidate set is every artwork of the exhibition whose `status` is `SHORTLISTED` **and** whose owning entry's `status` is `SUBMITTED`. Works belonging to a withdrawn entry, works already `DECLINED`, and works whose entry never cleared its fee are all outside the set. If the candidate set is empty the whole run is refused with `ERR_NO_ELIGIBLE_ARTWORKS` and no state changes at all — the exhibition stays in `JURYING`.

Candidates are then ranked by `certified_mean_score` descending, with ties broken by `created_at` ascending. A per-medium cap keeps one category from taking the whole show: the cap is the exhibition's `acceptance_capacity` multiplied by 0.40 and rounded **up** to a whole number, so a capacity of 3 permits 2 works per medium. Working down the ranking one candidate at a time, the server applies a strictly ordered two-part test. If the number of works accepted so far is below `acceptance_capacity` **and** the number already accepted in this candidate's `medium_category` is below the per-medium cap, the candidate is accepted and that medium's tally increases. Otherwise, if the number of works waitlisted so far is below `waitlist_capacity`, the candidate is waitlisted. Otherwise the candidate is declined. The global capacity test is evaluated before the medium cap for each candidate in rank order, which has a visible consequence: once a medium has filled its cap, that medium's next-ranked work falls to the waitlist even though global capacity remains open, and a lower-ranked work in a different medium takes the seat.

Each candidate's outcome is written as a transition on its own axis. `SHORTLISTED → ACCEPTED` for a work that fits within `acceptance_capacity` and within its medium's cap; `SHORTLISTED → WAITLISTED` for a work displaced by either the global capacity or its medium's cap but still ranked inside `waitlist_capacity`; and `SHORTLISTED → DECLINED` for a work ranked beyond `acceptance_capacity` plus `waitlist_capacity` combined. Every one of the three increments the work's `version`. The run then recomputes the exhibition's `accepted_count`, `waitlisted_count` and `shortlisted_count`, and increments the exhibition's `version` by 1. `accepted_count` is a broad measure, not a snapshot of the `ACCEPTED` state alone: it counts every work of the exhibition whose `status` is any of `ACCEPTED`, `DELIVERED`, `ON_VIEW`, `SOLD`, `RETURN_PENDING`, `RETURN_SCHEDULED`, `RETURNED` or `UNCLAIMED_FORFEIT`, so a work that has been delivered or sold still consumes a seat. `waitlisted_count` counts works currently holding `WAITLISTED`.

The run reports its own outcome rather than requiring the caller to re-query: `accepted_artwork_ids`, `waitlisted_artwork_ids` and `declined_artwork_ids` list the three groups, `accepted_count`, `waitlisted_count` and `declined_count` give their sizes, and `exhibition_status` reports the exhibition's phase after the run.

The waitlist is then worked by hand. A `JuryChair` may promote an individual `WAITLISTED` work `WAITLISTED → ACCEPTED` while the exhibition is either `RESULTS_PUBLISHED` or `INSTALLATION` — a promotion attempted in any other phase is refused with `ERR_EXHIBITION_PHASE_INVALID`. Promotion requires that `accepted_count` be strictly below `acceptance_capacity`, else `ERR_ACCEPTANCE_CAPACITY_REACHED`, and requires `expected_exhibition_version` to match. A successful promotion raises `accepted_count` by one and lowers `waitlisted_count` by one, and increments both the exhibition's `version` and the artwork's `version` by 1. Note that promotion is not bound by the per-medium cap — that cap governs the automated run only.

### 3.7. Delivery, Condition, Insurance, Wall Planning and Installation

Entering the installation phase is gated on two things beyond being in `RESULTS_PUBLISHED`: at least one wall segment must already be registered for the exhibition, else `ERR_WALL_SEGMENT_REQUIRED`, and the clock must not yet have passed `delivery_window_end_at`, else `ERR_DELIVERY_WINDOW_INVALID` — there is no point opening intake after the delivery window has expired.

Physical arrivals are recorded by a `Registrar` as **ConditionReport** records naming the inspection `stage`, either `INTAKE` on delivery or `DEINSTALL` on the way out; a `condition_grade` of `A`, `B`, `C` or `DAMAGED`; a `photo_count` of at least one documentation photograph; and, when the grade is `DAMAGED`, mandatory `damage_notes`. The filing registrar's opaque identity is stored as `reported_by_user_id`. An `INTAKE` report is the event that acknowledges delivery: it carries the work `ACCEPTED → DELIVERED`, requires the exhibition to be in `INSTALLATION`, and requires the clock to lie inside the closed `[delivery_window_start_at, delivery_window_end_at]` interval, else `ERR_DELIVERY_WINDOW_INVALID`. The work's `intake_condition_grade` is refreshed from the report: it is the `condition_grade` of the latest `INTAKE` report for that work when its reports are ordered by `created_at` ascending, so a re-inspection supersedes an earlier one, and it is null while no `INTAKE` report exists.

Delivery is also the moment insurance attaches, and the **premium assessment** re-runs whenever a work enters or leaves coverage — on an intake report, on the cascade that puts works on view, on the cascade that closes the show, and on a sale void. Coverage is defined by state: `insured_value_total_cents` is the sum of `declared_value_cents` over the exhibition's works whose `status` is `DELIVERED`, `ON_VIEW` or `SOLD`. Works still merely `ACCEPTED`, and works that have reached `RETURN_PENDING`, `RETURNED` or `UNCLAIMED_FORFEIT`, are outside coverage and contribute nothing. From that total the premium is derived in a pinned order. The insured total is divided by 100,000 cents — one thousand dollars — and rounded **up** to the next whole unit, and that rounding-up happens exactly once on the aggregate, never once per artwork. The resulting unit count is then allocated across three bands: the first 50 units at 350 cents each, the next 150 units (units 51 through 200) at 275 cents each, and every unit beyond 200 at 190 cents each. The three band products are summed into a raw premium. Finally the floor is applied — but only while coverage is actually in force. When `insured_value_total_cents` is greater than zero, `insurance_premium_cents` is the greater of 25,000 cents and the raw premium, so an insured total of 4,900,000 cents charges 25,000 rather than its raw 17,150. When `insured_value_total_cents` is exactly zero, the floor does **not** apply and `insurance_premium_cents` is 0 — an exhibition with nothing under coverage is charged nothing.

Hanging is planned before it is executed, and the plan is where wall space is actually reserved. A `Registrar` files an installation plan naming the `wall_segment_id`, the `span_start_cm` and `span_end_cm` of the requested span, and the wall's `expected_wall_segment_version`. The `span_end_cm` is the exclusive right edge of the reservation. Eight conditions gate the plan. The work must be `UNPLACED` on its placement axis and `DELIVERED` on its status axis, and the exhibition must be in `INSTALLATION`. The wall must belong to the same exhibition as the work, else `ERR_EXHIBITION_SCOPE_MISMATCH`. The work's `intake_condition_grade` must not be `DAMAGED`, else `ERR_ARTWORK_CONDITION_BLOCKED` — damaged work is not hung. The work's `declared_value_cents` must be at most the exhibition's `per_work_insurance_cap_cents`, else `ERR_INSURANCE_COVERAGE_MISSING`, because the policy will not cover it. The span must satisfy `span_start_cm` at least 0, strictly less than `span_end_cm`, and `span_end_cm` at most the wall's `length_cm`, else `ERR_WALL_SPAN_OUT_OF_BOUNDS`. The span must clear its neighbours by a **15-centimetre hanging buffer**: the plan is refused with `ERR_WALL_SPAN_CONFLICT` if, for any other artwork on the same wall whose `placement_status` is `PLANNED` or `INSTALLED`, the requested `span_start_cm` less 15 is smaller than that neighbour's `span_end_cm` while at the same time the requested `span_end_cm` plus 15 is greater than that neighbour's `span_start_cm`. A gap of exactly 15 centimetres between two spans is therefore legal and a gap of 14 is not. And the wall must bear the load: its `loaded_weight_kg` plus the work's `weight_kg` must be at most the wall's `max_weight_kg`, else `ERR_WALL_WEIGHT_EXCEEDED`.

A successful plan carries the work `UNPLACED → PLANNED`, stores its `wall_segment_id`, `span_start_cm` and `span_end_cm`, and recomputes the wall's three derived figures: `occupied_cm` as the sum of span widths over the artworks assigned to that wall whose `placement_status` is `PLANNED` or `INSTALLED`, `available_cm` as the wall's `length_cm` minus `occupied_cm`, and `loaded_weight_kg` as the sum of `weight_kg` over the same set. Both the wall's `version` and the artwork's `version` increment by 1. Marking the work physically hung then carries it `PLANNED → INSTALLED` and requires only that the exhibition still be in `INSTALLATION`.

Deinstallation is the compensating counterpart of the reservation and releases the centimetres. It is available from either `PLANNED` or `INSTALLED`, moves the work to `DEINSTALLED`, and recomputes the wall's `occupied_cm`, `available_cm` and `loaded_weight_kg` so that `occupied_cm` plus `available_cm` still equals `length_cm` — that pair is the conserved spatial quantity of the system. When the work's status axis has reached `ON_VIEW` or `RETURN_PENDING`, a `DEINSTALL`-stage condition report must already exist for it, else the deinstall is refused with `ERR_CONDITION_REPORT_REQUIRED`. The work's `wall_segment_id` is retained after deinstall as a record of where it hung.

Opening the show to the public is the compound gate of the whole installation phase. Advancing `INSTALLATION → ON_VIEW` requires that **every** artwork of the exhibition whose `status` is `ACCEPTED` or `DELIVERED` have `placement_status` `INSTALLED`, else `ERR_INSTALLATION_INCOMPLETE`, and requires the clock to have reached `opening_at`, else `ERR_PHASE_TIME_NOT_REACHED`. The advance then cascades: every work whose `status` is `DELIVERED` and whose `placement_status` is `INSTALLED` moves `DELIVERED → ON_VIEW`, each incrementing its own `version`.

### 3.8. Recognising Sponsors and Awarding Prizes

A `CallManager` registers each **Sponsor** against an `exhibition_id` with the `name` recognised in print, a cash `contribution_cents`, and a `purchase_award_budget_cents` ceiling on the purchase awards that sponsor may fund. The `recognition_tier` is derived from the contribution against four inclusive floors: a contribution of at least 5,000,000 cents is `PRESENTING`; at least 2,500,000 is `GOLD`; at least 1,000,000 is `SILVER`; at least 250,000 is `BRONZE`; anything below that is `NONE`. Every floor is inclusive, so 999,999 cents is `BRONZE` while exactly 1,000,000 is `SILVER`. The tier is re-derived on any change to `contribution_cents`. A new sponsor's `purchase_award_committed_cents` — the sum of `prize_cents` over that sponsor's `CONFIRMED` awards — starts at 0.

An **Award** is proposed by a `JuryChair` naming the `exhibition_id`, the `artwork_id` being honoured, a `category` of `BEST_IN_SHOW`, `JURORS_CHOICE`, `MEDIUM_MERIT` or `PURCHASE_AWARD`, and a cash `prize_cents`. A `sponsor_id` is optional in general but mandatory when the `category` is `PURCHASE_AWARD`, where the `prize_cents` is simultaneously the prize and the purchase price. The award is created at `status` `PROPOSED` with `proposed_by_user_id` set to the acting chair's opaque identity. Both at proposal and again at confirmation, the honoured work must belong to the award's exhibition and the named sponsor must belong to that same exhibition, else `ERR_EXHIBITION_SCOPE_MISMATCH`.

Confirmation is a separate act by a **different** chair, advancing the award `PROPOSED → CONFIRMED`, and it is where the money is committed. The exhibition must be in `RESULTS_PUBLISHED`, `INSTALLATION` or `ON_VIEW`. The confirming identity must differ from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Two budget tests then apply, each to its own kind of award: for an award with no sponsor, the exhibition's `award_committed_cents` plus this award's `prize_cents` must be at most `award_budget_cents`, else `ERR_AWARD_BUDGET_EXCEEDED`; and for a `PURCHASE_AWARD`, the sponsor's `purchase_award_committed_cents` plus this award's `prize_cents` must be at most that sponsor's `purchase_award_budget_cents`, else `ERR_SPONSOR_BUDGET_EXCEEDED`. A `PURCHASE_AWARD` additionally requires the honoured work to be `ON_VIEW` — the council does not sell what is not hanging. Finally the chair must quote `expected_exhibition_version`. On success the award records `confirmed_by_user_id`, and either the exhibition's `award_committed_cents` — the sum of `prize_cents` over `CONFIRMED` awards with no sponsor — or the sponsor's `purchase_award_committed_cents` is recomputed. The exhibition's `version` and the award's `version` each increment by 1.

Confirming a `PURCHASE_AWARD` cascades three hops into the sales ledger, because a purchase award *is* a sale. First, a **Sale** is created with `sale_type` `PURCHASE_AWARD`, its `source_award_id` pointing at this award, its `sale_price_cents` equal to the award's `prize_cents`, its `buyer_name` taken from the sponsor's `name`, and `status` `RECORDED`; its settlement split is computed by the same rules as any other sale, in the tax-additional variant described in §3.9. Second, the created sale drives the honoured work `ON_VIEW → SOLD` with `sold_price_cents` set to the award's `prize_cents`. Third, the work becoming `SOLD` drives a recompute of the exhibition's `sales_gross_cents`, `commission_total_cents`, `sales_tax_total_cents` and `artist_payable_total_cents`.

An award may be rescinded by a `JuryChair` while the exhibition's `settlement_status` is still `NOT_STARTED`, else `ERR_SETTLEMENT_PHASE_INVALID`. Rescission requires a `reason`, carries the award `CONFIRMED → RESCINDED`, and recomputes the relevant commitment figure — the exhibition's `award_committed_cents` or the sponsor's `purchase_award_committed_cents` — downward. For a `PURCHASE_AWARD` it also unwinds the sale: the linked sale moves to `VOIDED` and its artwork returns to `ON_VIEW`. An award that is not `PROPOSED` when confirmation is requested, or not `CONFIRMED` when rescission is requested, is refused with `ERR_AWARD_STATE_INVALID`.

### 3.9. Sales, Tax, Commission and Artist Payment

A `FinanceOfficer` records a gallery **Sale** naming the `artwork_id`, the `buyer_name`, the `buyer_region_code` kept for tax reporting, the `sale_price_cents` charged to the buyer, and optionally `tax_exempt`, which is false by default. The sale is created with `sale_type` `GALLERY_SALE`, `status` `RECORDED`, and `recorded_by_user_id` set to the acting officer's opaque identity. The work must be `ON_VIEW`, must have `for_sale` true with a `list_price_cents` posted — otherwise `ERR_ARTWORK_NOT_FOR_SALE` — and must not already carry a sale in any state other than `VOIDED`. Recording the sale carries the work `ON_VIEW → SOLD` and sets its `sold_price_cents` to the sale's `sale_price_cents`. The `source_award_id` of a counter sale stays null; it is populated only on the sale cascaded from a confirmed purchase award.

The **settlement split** is computed once, at the moment the sale row is created, in a pinned order: the taxable base first, then the tax, then the commission on that base, then the artist's share, then the buyer's total. The base and tax depend on which of three cases applies. When `tax_exempt` is true, `taxable_base_cents` is the whole `sale_price_cents` and `sales_tax_cents` is 0. When the sale is a `GALLERY_SALE` that is not tax-exempt, the posted price is understood to **include** tax: `taxable_base_cents` is `sale_price_cents` divided by one plus the exhibition's `sales_tax_pct`, rounded half up to whole cents, and `sales_tax_cents` is the residual, `sale_price_cents` minus `taxable_base_cents`, so no cent is created or lost in the split. When the sale is a `PURCHASE_AWARD` that is not tax-exempt, the price is **tax-additional**: `taxable_base_cents` is the whole `sale_price_cents`, and `sales_tax_cents` is `sale_price_cents` multiplied by the exhibition's `sales_tax_pct`, rounded half up to whole cents.

The commission rate then depends on the sale's kind, not on the exhibition alone: a `PURCHASE_AWARD` is commissioned at a flat 0.10, while a `GALLERY_SALE` is commissioned at the exhibition's `commission_pct`. `commission_cents` is `taxable_base_cents` multiplied by that rate, rounded half up to whole cents. `artist_payable_cents` is `taxable_base_cents` minus `commission_cents`. And `buyer_total_cents` is `taxable_base_cents` plus `sales_tax_cents` — the figure a buyer payment must match exactly. The two variants diverge sharply on identical numbers: a `sale_price_cents` of 250,000 at a `sales_tax_pct` of 0.0875 and a `commission_pct` of 0.35 gives, as a tax-inclusive gallery sale, a base of 229,885, tax of 20,115, commission of 80,460, an artist payable of 149,425 and a buyer total of 250,000; the same 250,000 as a tax-additional purchase award gives a base of 250,000, tax of 21,875, commission of 25,000, an artist payable of 225,000 and a buyer total of 271,875 — the artist nets 75,575 cents more from the same headline price.

The sale then walks a four-step ladder. Issuing the buyer invoice carries it `RECORDED → INVOICED`. Recording buyer payment carries it `INVOICED → PAID` and requires the tendered `amount_cents` to equal `buyer_total_cents` exactly, else `ERR_PAYMENT_AMOUNT_MISMATCH`. Releasing the artist's money carries it `PAID → PAYOUT_RELEASED` and is the most heavily gated operation in the system: the exhibition's `settlement_status` must be `RECONCILING`, else `ERR_SETTLEMENT_PHASE_INVALID`; the artist must have `tax_form_on_file` true, else `ERR_TAX_FORM_MISSING`; the artist's `payout_hold` must be false, else `ERR_ARTIST_PAYOUT_HOLD`; the releasing identity must differ from `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; and `expected_exhibition_version` must match. On success the sale records `payout_released_by_user_id`, the exhibition's `payouts_released_cents` — the sum of `artist_payable_cents` over that exhibition's sales at `PAYOUT_RELEASED` — is recomputed, and both the exhibition's `version` and the sale's `version` increment by 1. A sale whose state does not admit the requested step is refused with `ERR_SALE_STATE_INVALID`.

Voiding is the compensating transition that keeps the money invariant honest. A `FinanceOfficer` may void a sale from `RECORDED`, `INVOICED` or `PAID`, supplying a `reason` that is stored as `void_reason`, and only while the exhibition's `settlement_status` is `NOT_STARTED` or `RECONCILING`. A sale that has already reached `PAYOUT_RELEASED` can no longer be voided. Voiding releases the artwork: when the sale was that work's only non-voided sale and the exhibition is still `ON_VIEW`, the work returns `SOLD → ON_VIEW` with `sold_price_cents` cleared to null; when the exhibition has already reached `CLOSED`, the work returns to `RETURN_PENDING` instead. Either way the exhibition's `sales_gross_cents`, `commission_total_cents`, `sales_tax_total_cents` and `artist_payable_total_cents` are recomputed back to their pre-sale values. Those four aggregates are always taken over the exhibition's sales whose `status` is `RECORDED`, `INVOICED`, `PAID` or `PAYOUT_RELEASED` — voided sales are excluded entirely — and they are, respectively, the sums of `sale_price_cents`, `commission_cents`, `sales_tax_cents` and `artist_payable_cents` over that set.

### 3.10. Closing the Show: Returns, Forfeiture and Settlement

Closing the exhibition is the last advance on the phase axis and requires only that the clock have reached `closing_at`, else `ERR_PHASE_TIME_NOT_REACHED`. `ON_VIEW → CLOSED` cascades four hops. First, every work whose `status` is `ON_VIEW` moves to `RETURN_PENDING`, and its `claim_deadline_at` is stamped as the exhibition's `closing_at` plus `claim_deadline_days` days. Second, each work entering `RETURN_PENDING` whose `placement_status` is `INSTALLED` moves to `DEINSTALLED`. Third, each work entering `DEINSTALLED` drives a recompute of its wall segment's `occupied_cm`, `available_cm` and `loaded_weight_kg`. Fourth, the resulting drop in the insured set drives a recompute of `insured_value_total_cents` and then of `insurance_premium_cents`.

Returns are arranged work by work by a `Registrar`. Arranging a shipment carries the work `RETURN_PENDING → RETURN_SCHEDULED` and requires that a `DEINSTALL`-stage condition report already exist for it, else `ERR_CONDITION_REPORT_REQUIRED`. The request names a `return_method` of either `ARTIST_PICKUP` or `COURIER`; a `COURIER` return additionally requires both a `carrier` and a `tracking_number`, which are stored on the work as `return_carrier` and `return_tracking_number`. Recording the handover then carries the work `RETURN_SCHEDULED → RETURNED` and freezes its `storage_fee_cents` at whatever value the last sweep left there.

Unclaimed work is handled by a periodic sweep that a `Registrar` runs against the exhibition at the current logical clock. The sweep considers the exhibition's works whose `status` is `RETURN_PENDING` or `RETURN_SCHEDULED`, whose `return_method` is either null or `ARTIST_PICKUP`, and whose `claim_deadline_at` is at or before the clock. Works on a `COURIER` return are deliberately excluded, because the council controls that transit and cannot hold the artist responsible for it. For each work in scope, the number of overdue days is the whole number of 86,400-second days elapsed since `claim_deadline_at`, truncated downward, **plus one** — the deadline day itself counts as day one, so a sweep run at exactly `claim_deadline_at` already accrues one day. The work's `storage_fee_cents` is then the lesser of two figures: 1,500 cents multiplied by the overdue-day count, and half of the work's `declared_value_cents` truncated downward. The fee is thus capped at 50 percent of the declared value however long the work sits. When the overdue-day count exceeds a grace period of 30 days — strictly greater than 30, so day 31 is the first forfeiting day — the work moves `RETURN_PENDING → UNCLAIMED_FORFEIT` and the council takes title. The same forfeiture applies to a work sitting in `RETURN_SCHEDULED` whose `return_method` is not `COURIER`.

Forfeiture cascades onto the artist's payment standing in three hops. First, the artist's `unclaimed_forfeit_count` — the number of their works at `UNCLAIMED_FORFEIT` across **all** exhibitions, not just this one — is recomputed. Second, when that count reaches 2, the artist's `payout_hold` is set to true. Third, any later attempt to release an artist payout for that artist is refused with `ERR_ARTIST_PAYOUT_HOLD` until a `CallManager` clears the hold. The sweep reports `swept_artwork_ids` for the works it touched, `forfeited_artwork_ids` for the subset it forfeited, `storage_fee_total_cents` for the fees it accrued, and `swept_at` for the instant it ran.

Settlement is the exhibition's second, independent axis, driven by a `FinanceOfficer` naming a `target_settlement_status`, and it advances `NOT_STARTED → RECONCILING → PAYOUTS_RELEASED → BOOKS_CLOSED`. Reconciliation may begin only once the show is `ON_VIEW` or `CLOSED`, else `ERR_EXHIBITION_PHASE_INVALID`, and it recomputes `sales_gross_cents`, `commission_total_cents`, `sales_tax_total_cents`, `artist_payable_total_cents` and `council_retention_cents`. Advancing to `PAYOUTS_RELEASED` requires that no sale of the exhibition still sit at `RECORDED` or `INVOICED` — every non-voided sale must have reached `PAID` or `PAYOUT_RELEASED` — and that `payouts_released_cents` equal `artist_payable_total_cents` exactly, else `ERR_PAYOUT_INCOMPLETE`. Closing the books requires the show itself to be `CLOSED`, else `ERR_EXHIBITION_PHASE_INVALID`, and freezes `council_retention_cents`. Every settlement advance increments the exhibition's `version` by 1.

The **retention figure** is what the council actually keeps, and its evaluation order is pinned to break an apparent circularity. Step one sums `sale_price_cents` over the exhibition's non-voided sales into `sales_gross_cents`. Step two sums, over that same set, `commission_cents` into `commission_total_cents`, `sales_tax_cents` into `sales_tax_total_cents`, and `artist_payable_cents` into `artist_payable_total_cents`. Step three takes the premium already computed as `insurance_premium_cents`. Step four selects a premium-recovery rate **keyed on the commission total from step two, never on the retention figure being computed**: the rate is 0.75 when `commission_total_cents` is at least 150,000 cents, otherwise 0.50 when it is at least 50,000 cents, otherwise 0.25. Step five sets `council_retention_cents` to `commission_total_cents` minus the premium multiplied by that recovery rate, with only that recovered-premium product rounded half up to whole cents. Keying the tier on the retention figure instead of the commission would be self-referential and is explicitly not the rule. Note also that `council_retention_cents` may legitimately be negative when commission is small relative to the premium; the system does not floor it at zero. Alongside it, `jury_cost_committed_cents` records what the jury has cost — the sum of `honorarium_share_cents` over the `BOOKED` and `COMPLETED` assignments of every round belonging to this exhibition.

## 4. Endpoint Definitions

Requests that create a new resource answer with HTTP 201; every other successful request answers with HTTP 200. Request and response payloads are not restated here — the fields each operation accepts, the derived values it writes, and the cascades it triggers are specified in §3, and the errors it can return follow from the precedence ladder in §2.10.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| `POST` | `/exhibitions` | Create an exhibition (call for entries configuration) in `DRAFT` / `NOT_STARTED`. | `CallManager` |
| `GET` | `/exhibitions` | List exhibitions with pagination and optional status filter. | `CallManager`, `JuryChair`, `Juror`, `Artist`, `Registrar`, `FinanceOfficer` |
| `GET` | `/exhibitions/{id}` | Read one exhibition including every computed money and count field; the source of the exhibition version clients quote back. | `CallManager`, `JuryChair`, `Juror`, `Artist`, `Registrar`, `FinanceOfficer` |
| `POST` | `/exhibitions/{id}/phase-advance` | Advance the exhibition's lifecycle axis (`OPEN_FOR_ENTRIES`, `JURYING`, `INSTALLATION`, `ON_VIEW`, `CLOSED`); `RESULTS_PUBLISHED` is reachable only through the acceptance-list run. | `CallManager` |
| `POST` | `/exhibitions/{id}/acceptance-list` | Determine the acceptance list, fork every `SHORTLISTED` artwork to `ACCEPTED` / `WAITLISTED` / `DECLINED`, and move the exhibition to `RESULTS_PUBLISHED`. | `JuryChair` |
| `POST` | `/exhibitions/{id}/settlement` | Advance the exhibition's settlement axis (`RECONCILING`, `PAYOUTS_RELEASED`, `BOOKS_CLOSED`). | `FinanceOfficer` |
| `POST` | `/exhibitions/{id}/unclaimed-sweep` | Accrue storage fees on unclaimed work at the current logical clock and forfeit works past the grace period. | `Registrar` |
| `POST` | `/artists` | Register an artist in the council roster. | `CallManager` |
| `GET` | `/artists/{id}` | Read one artist including payout eligibility fields. | `CallManager`, `Artist`, `FinanceOfficer` |
| `PATCH` | `/artists/{id}` | Update artist administrative fields; a `CallManager` may also clear a payout hold. | `CallManager`, `Artist` |
| `GET` | `/artists/{id}/conflict-declarations` | Reverse lookup of every conflict declaration naming this artist. | `CallManager`, `JuryChair` |
| `POST` | `/entries` | Open a `DRAFT` entry for the acting artist against an `OPEN_FOR_ENTRIES` call. | `Artist` |
| `GET` | `/entries` | Filtered list of entries by exhibition, artist and status. | `CallManager`, `JuryChair`, `Artist` |
| `GET` | `/entries/{id}` | Read one entry including its frozen fee assessment. | `CallManager`, `JuryChair`, `Artist` |
| `POST` | `/entries/{id}/artworks` | Attach an artwork to a `DRAFT` entry; enforces media category, size limits and per-entry work count. | `Artist` |
| `POST` | `/entries/{id}/submit` | Submit the entry: freeze the assessed fee and move to `PENDING_FEE`. | `Artist` |
| `POST` | `/entries/{id}/fee-payment` | Pay the assessed entry fee exactly; cascades every `DRAFT` artwork of the entry to `SUBMITTED`. | `Artist` |
| `POST` | `/entries/{id}/fee-waiver` | Waive the entry fee (hardship policy) and admit the entry directly to `SUBMITTED`. | `CallManager` |
| `POST` | `/entries/{id}/withdraw` | Withdraw the entry before results; cascades its non-accepted artworks to `WITHDRAWN`. | `Artist`, `CallManager` |
| `GET` | `/artworks` | Filtered list of artworks by entry, exhibition, wall segment, status and placement status. | `CallManager`, `JuryChair`, `Juror`, `Artist`, `Registrar`, `FinanceOfficer` |
| `GET` | `/artworks/{id}` | Read one artwork; for a `Juror` reader during an open `BLIND_SCORING` round the entry key is masked and the blind label is the only identifier. | `CallManager`, `JuryChair`, `Juror`, `Artist`, `Registrar`, `FinanceOfficer` |
| `POST` | `/artworks/{id}/images` | Upload an image record; enforces the digital image standard and the metadata requirements. | `Artist` |
| `GET` | `/artworks/{id}/images` | Reverse lookup of the artwork's image records. | `CallManager`, `JuryChair`, `Juror`, `Artist` |
| `POST` | `/artworks/{id}/condition-reports` | File an `INTAKE` (delivery) or `DEINSTALL` condition report; an `INTAKE` report drives `ACCEPTED → DELIVERED`. | `Registrar` |
| `GET` | `/artworks/{id}/condition-reports` | Reverse lookup of the artwork's condition reports. | `CallManager`, `Registrar`, `FinanceOfficer`, `Artist` |
| `POST` | `/artworks/{id}/promotion` | Promote a `WAITLISTED` artwork to `ACCEPTED` against remaining capacity. | `JuryChair` |
| `POST` | `/artworks/{id}/installation-plan` | Reserve a buffered wall span for a delivered artwork. | `Registrar` |
| `POST` | `/artworks/{id}/install` | Mark a planned artwork physically installed. | `Registrar` |
| `POST` | `/artworks/{id}/deinstall` | Deinstall an artwork and release its wall span. | `Registrar` |
| `POST` | `/artworks/{id}/return-shipment` | Arrange the return of unsold work (artist pickup or courier). | `Registrar` |
| `POST` | `/artworks/{id}/return-completion` | Record that the work was collected or delivered back to the artist. | `Registrar` |
| `POST` | `/jurors` | Invite a juror with declared expertise and honorarium terms. | `JuryChair` |
| `GET` | `/jurors/{id}` | Read one juror including honorarium commitment and payment state. | `JuryChair`, `Juror`, `FinanceOfficer` |
| `POST` | `/jurors/{id}/confirm` | Juror accepts the invitation (`INVITED → CONFIRMED`). | `Juror`, `JuryChair` |
| `POST` | `/jurors/{id}/conflict-declarations` | Declare a conflict of interest with an artist; retroactively voids that juror's scores on the artist's works. | `Juror`, `JuryChair` |
| `GET` | `/jurors/{id}/conflict-declarations` | Reverse lookup of this juror's conflict declarations. | `Juror`, `JuryChair` |
| `POST` | `/jurors/{id}/resign` | Juror resigns; cancels their booked sessions and re-prorates their honorarium. | `Juror`, `JuryChair` |
| `POST` | `/jurors/{id}/honorarium-payment` | Remit honorarium to a juror up to their committed share. | `FinanceOfficer` |
| `POST` | `/jury-rounds` | Create a jury round (blind scoring or deliberation) for an exhibition. | `JuryChair` |
| `GET` | `/jury-rounds` | Filtered list of jury rounds by exhibition and status. | `CallManager`, `JuryChair`, `Juror` |
| `GET` | `/jury-rounds/{id}` | Read one jury round including its quorum shortfall; the source of the round version clients quote back. | `CallManager`, `JuryChair`, `Juror` |
| `POST` | `/jury-rounds/{id}/status` | Drive the round machine: `OPEN`, `SCORING_COMPLETE`, `OPEN` again (reopen, at most twice) or `CLOSED`. | `JuryChair` |
| `POST` | `/jury-rounds/{id}/assignments` | Book a confirmed juror into a session window of this round. | `JuryChair` |
| `GET` | `/juror-assignments` | Filtered list of assignments by juror, round and status. | `JuryChair`, `Juror`, `FinanceOfficer` |
| `GET` | `/juror-assignments/{id}` | Read one assignment including its prorated honorarium share. | `JuryChair`, `Juror`, `FinanceOfficer` |
| `POST` | `/juror-assignments/{id}/cancel` | Cancel a booked session; re-prorates the juror's honorarium so the pool stays conserved. | `JuryChair` |
| `POST` | `/jury-rounds/{id}/scores` | Submit one score for one artwork as the acting juror. | `Juror` |
| `GET` | `/scores` | Filtered list of scores by round, artwork and juror. | `JuryChair`, `Juror` |
| `GET` | `/scores/{id}` | Read one score including its expertise cap outcome. | `JuryChair`, `Juror` |
| `POST` | `/wall-segments` | Register a gallery wall segment for an exhibition. | `CallManager`, `Registrar` |
| `GET` | `/wall-segments` | Filtered list of wall segments by exhibition. | `CallManager`, `Registrar`, `JuryChair` |
| `GET` | `/wall-segments/{id}` | Read one wall segment including occupancy; the source of the wall version clients quote back. | `CallManager`, `Registrar`, `JuryChair` |
| `POST` | `/sponsors` | Register a sponsor; the recognition tier is derived from the contribution. | `CallManager` |
| `GET` | `/sponsors` | Filtered list of sponsors by exhibition and recognition tier. | `CallManager`, `JuryChair`, `FinanceOfficer` |
| `GET` | `/sponsors/{id}` | Read one sponsor including recognition tier and committed purchase awards. | `CallManager`, `JuryChair`, `FinanceOfficer` |
| `POST` | `/awards` | Propose an award for an artwork; records the proposing chair for segregation of duties. | `JuryChair` |
| `GET` | `/awards` | Filtered list of awards by exhibition, artwork, sponsor and status. | `CallManager`, `JuryChair`, `FinanceOfficer` |
| `GET` | `/awards/{id}` | Read one award including its proposer and confirmer. | `CallManager`, `JuryChair`, `FinanceOfficer` |
| `POST` | `/awards/{id}/confirm` | Confirm a proposed award by a different chair; a `PURCHASE_AWARD` cascades into a sale and marks the work `SOLD`. | `JuryChair` |
| `POST` | `/awards/{id}/rescind` | Rescind a confirmed award, releasing the budget commitment and voiding any purchase-award sale. | `JuryChair` |
| `POST` | `/sales` | Record a gallery sale of a work on view (tax-inclusive posted price). | `FinanceOfficer` |
| `GET` | `/sales` | Filtered list of sales by artwork, source award and status. | `CallManager`, `FinanceOfficer`, `Artist` |
| `GET` | `/sales/{id}` | Read one sale including the full commission, tax and payable split. | `CallManager`, `FinanceOfficer`, `Artist` |
| `POST` | `/sales/{id}/invoice` | Issue the buyer invoice (`RECORDED → INVOICED`). | `FinanceOfficer` |
| `POST` | `/sales/{id}/payment` | Record buyer payment of exactly the buyer total (`INVOICED → PAID`). | `FinanceOfficer` |
| `POST` | `/sales/{id}/payout` | Release the artist payment for a paid sale; requires a different officer than the recorder. | `FinanceOfficer` |
| `POST` | `/sales/{id}/void` | Void a sale that has not yet paid out; restores the artwork and every exhibition money aggregate. | `FinanceOfficer` |
| `POST` | `/_clock/set_current_utc` | Set the server's logical clock. Before any call the logical clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time. | `CallManager`, `JuryChair`, `Juror`, `Artist`, `Registrar`, `FinanceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_EXHIBITION_NOT_FOUND` | 404 |
| `ERR_ARTIST_NOT_FOUND` | 404 |
| `ERR_ENTRY_NOT_FOUND` | 404 |
| `ERR_ARTWORK_NOT_FOUND` | 404 |
| `ERR_JUROR_NOT_FOUND` | 404 |
| `ERR_JURY_ROUND_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_WALL_SEGMENT_NOT_FOUND` | 404 |
| `ERR_SPONSOR_NOT_FOUND` | 404 |
| `ERR_AWARD_NOT_FOUND` | 404 |
| `ERR_SALE_NOT_FOUND` | 404 |
| `ERR_SCORE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ENTRY_STATE_INVALID` | 409 |
| `ERR_ARTWORK_STATE_INVALID` | 409 |
| `ERR_JURY_ROUND_STATE_INVALID` | 409 |
| `ERR_AWARD_STATE_INVALID` | 409 |
| `ERR_SALE_STATE_INVALID` | 409 |
| `ERR_ASSIGNMENT_STATE_INVALID` | 409 |
| `ERR_EXHIBITION_PHASE_INVALID` | 409 |
| `ERR_SETTLEMENT_PHASE_INVALID` | 409 |
| `ERR_JUROR_NOT_CONFIRMED` | 409 |
| `ERR_ROUND_REOPEN_LIMIT` | 409 |
| `ERR_EXHIBITION_SCOPE_MISMATCH` | 422 |
| `ERR_ARTWORK_NOT_FOR_SALE` | 422 |
| `ERR_JUROR_CONFLICT_DECLARED` | 403 |
| `ERR_CONDITION_REPORT_REQUIRED` | 409 |
| `ERR_ARTWORK_CONDITION_BLOCKED` | 422 |
| `ERR_INSURANCE_COVERAGE_MISSING` | 409 |
| `ERR_TAX_FORM_MISSING` | 422 |
| `ERR_ARTIST_PAYOUT_HOLD` | 409 |
| `ERR_CALL_WINDOW_CLOSED` | 409 |
| `ERR_CALL_WINDOW_NOT_CLOSED` | 409 |
| `ERR_SCORING_WINDOW_CLOSED` | 409 |
| `ERR_SESSION_OUTSIDE_ROUND_WINDOW` | 422 |
| `ERR_JUROR_SESSION_OVERLAP` | 409 |
| `ERR_DELIVERY_WINDOW_INVALID` | 409 |
| `ERR_PHASE_TIME_NOT_REACHED` | 409 |
| `ERR_ELIGIBILITY_NOT_MET` | 422 |
| `ERR_MEDIA_CATEGORY_NOT_ALLOWED` | 422 |
| `ERR_SIZE_LIMIT_EXCEEDED` | 422 |
| `ERR_MAX_WORKS_EXCEEDED` | 422 |
| `ERR_ENTRY_LIMIT_EXCEEDED` | 409 |
| `ERR_IMAGE_STANDARD_VIOLATION` | 422 |
| `ERR_IMAGE_METADATA_INCOMPLETE` | 422 |
| `ERR_PRIMARY_IMAGE_REQUIRED` | 409 |
| `ERR_DUPLICATE_ROUND_NUMBER` | 409 |
| `ERR_DUPLICATE_SCORE` | 409 |
| `ERR_QUORUM_NOT_MET` | 409 |
| `ERR_NO_ELIGIBLE_ARTWORKS` | 409 |
| `ERR_ACCEPTANCE_CAPACITY_REACHED` | 409 |
| `ERR_WALL_SPAN_OUT_OF_BOUNDS` | 422 |
| `ERR_WALL_SPAN_CONFLICT` | 409 |
| `ERR_WALL_WEIGHT_EXCEEDED` | 422 |
| `ERR_INSTALLATION_INCOMPLETE` | 409 |
| `ERR_WALL_SEGMENT_REQUIRED` | 409 |
| `ERR_FEE_AMOUNT_MISMATCH` | 402 |
| `ERR_AWARD_BUDGET_EXCEEDED` | 402 |
| `ERR_SPONSOR_BUDGET_EXCEEDED` | 402 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 402 |
| `ERR_PAYOUT_INCOMPLETE` | 409 |
| `ERR_STALE_VERSION` | 412 |
