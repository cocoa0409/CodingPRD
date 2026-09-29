# Municipal Clerk Records & Ordinance Codification API — Product Requirements Document

## 1. Introduction

A city clerk's office is the only place in municipal government where the legal record actually becomes legal. A meeting is not a meeting until notice has been posted far enough in advance; a vote is not an official act until the minutes carrying it have been approved at a *later* meeting; an ordinance is not law until it has been numbered, published in a newspaper of record, and — when it touches the municipal code — carried into a certified supplement. Every one of those steps has a statutory clock attached to it, and every one of them can be undone: packets are withdrawn and re-posted, minutes are corrected, vetoes are overridden, destruction certificates are rescinded. Clerks today reconcile these clocks by hand across a calendar, a numbering ledger, a newspaper invoice file, a retention schedule and a public-records log that do not talk to each other.

This document specifies the Municipal Clerk Records & Ordinance Codification API, a single service that holds all of those registers and enforces the arithmetic between them. The service is mounted under `/clerk`. Its design premise is that derived facts are never entered by hand: notice hours, notice deadlines, vote thresholds, assigned instrument numbers, effective dates, newspaper invoices, response deadlines, fee balances and retention eligibility dates are all computed by the server from the primary facts the clerk records, and are recomputed rather than patched whenever a primary fact moves. A second premise is that the record must be reconstructible after the fact: voided publication notices keep their invoice arithmetic, rescinded destruction certificates keep the identity of the officer who signed them, and rejected codification submissions keep the precedence rule that defeated them.

Because the office is small and its acts are consequential, the service also encodes separation of responsibilities directly into the API surface. The clerk notices meetings and tallies votes; the presiding officer convenes, adjourns, breaks ties and vetoes; the records officer owns the retention schedule, exemption review and fee waivers; the codification editor owns the supplement pipeline. Two operations — signing a certificate of destruction and certifying a supplement into the code — additionally refuse to accept the same human who performed the paired earlier step. Read this document as a description of a municipal office whose procedures happen to be executable, not as an API reference: the endpoint table in section 4 is deliberately thin, and the rules that govern each endpoint live in the narrative of sections 2 and 3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the service must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the capacity in which it acts. If either header is absent, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request is examined. If `X-User-Role` carries a value that is not one of the seven role names defined below, the rejection is `ERR_UNKNOWN_ROLE`, also HTTP 401. Only once the role is recognised does the service ask whether that role is permitted on the endpoint being called; if it is not, the answer is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The seven roles are `CityClerk`, `DeputyClerk`, `PresidingOfficer`, `RecordsOfficer`, `CodificationEditor`, `Requester` and `Anonymous`, spelled exactly as shown.

- A `CityClerk` is the custodian of the official record. The clerk registers venues and numbering series, schedules, reschedules and cancels meetings, creates and posts agenda packets, withdraws them, submits minutes, tallies motions, introduces instruments and advances their readings, certifies newspaper publication, and closes public records requests.
- A `DeputyClerk` prepares the record but cannot notice a meeting, tally a vote, certify a publication or close a request. The deputy may add agenda items, write and correct minutes narratives, record motions, place insertion orders, intake and begin review of records requests, assess fees, accession records into custody and propose destruction batches.
- A `PresidingOfficer` is the mayor or chair. This role calls a meeting to order, adjourns it, supplies the tie-breaking vote and exercises the veto, and otherwise never touches the record itself.
- A `RecordsOfficer` owns the retention schedule, statutory exemption review, fee waivers and the rescission of destruction certificates.
- A `CodificationEditor` is the code publisher's editor: it creates code titles, opens supplement cycles, files and decides codification submissions, resolves old-versus-new provision conflicts and certifies the supplement into the code.
- A `Requester` is a member of the public who has already filed a records request and acts on it afterwards.
- An `Anonymous` caller is an unauthenticated member of the public whose only permitted act is filing a new records request.

Six of the seven roles carry an **opaque** identity. When `X-User-Role` is `CityClerk`, `DeputyClerk`, `PresidingOfficer`, `RecordsOfficer`, `CodificationEditor` or `Anonymous`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it (for example as `proposed_by_officer_id` and `certifying_officer_id` on a destruction batch, or as `resolved_by_user_id` on a codification submission, where the workflows in section 3 write it) but it never compares that value to any entity's `id` for the purpose of ownership.

The `Requester` role is the single exception and is **entity-backed by `PublicRecordsRequest`**. When `X-User-Role` is `Requester`, `X-User-ID` is the `id` of the acting `PublicRecordsRequest` — the identifier returned in the body of the intake response — and ownership checks compare the request identified in the path to `X-User-ID`. This check guards exactly three operations: reading a single records request, recording a payment against it, and withdrawing it. On any of those three, a `Requester` whose `X-User-ID` differs from the `request_id` in the path is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The ownership check runs after the role check and before any existence, shape or state checks on the body.

Two operations impose a further identity constraint that is not about roles but about *which human* is acting. Signing a certificate of destruction and certifying a supplement cycle both refuse an actor who performed the paired earlier step, and both report `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); section 2.8 states the rule precisely.

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

Every collection endpoint accepts two query parameters. `limit` controls page size: it defaults to 10, may not be below 1, and may not exceed 100. `offset` controls the starting position: it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422).

Unless a specific listing states otherwise, collections are returned sorted by `created_at` ascending, so that the oldest record appears first and paging through a collection is stable. The one documented deviation is the item listing of a single agenda packet, which is returned in `sequence_number` order because that is the order the agenda is printed in.

List responses populate `limit`, `offset`, `total_count` and `has_more` inside `meta`. `total_count` reports the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records matching the filters remain beyond the current page.

### 2.4. The Logical Clock

Nothing in this domain reads wall-clock time. Notice deadlines, publication windows, submission windows, business-day walks, retention anchors and every timestamp the server stamps onto a record are all read from a single server-held **logical clock**. Before any caller sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never fall back to the host's real time.

`POST /clerk/_clock/set_current_utc` moves the clock to an arbitrary instant supplied as `to_iso8601` and answers with the resulting `current_utc`. The call mutates no entity — it only changes what subsequent requests read as "now" — and it is available to `CityClerk`, `DeputyClerk`, `PresidingOfficer`, `RecordsOfficer` and `CodificationEditor`. Where this document says an instant or a date is "the logical clock instant" or "the logical clock date", it means the value this clock currently reports, with the date being the calendar date of that instant in UTC.

### 2.5. Common Resource Properties

Every resource the service persists carries a server-minted `id`, which is a UUID with no type prefix of any kind, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits, recording when the record was first stored.

Most resources additionally carry `updated_at`, in the same timestamp format, and `version`, an integer that begins at 1 when the record is created and increases by exactly 1 on every mutation of that record. Whenever a workflow in section 3 says a field is written, cleared or recomputed on a resource, that resource's `updated_at` is refreshed and its `version` advances — including when the write arrives as a cascade from an operation performed against a different resource. `Venue`, `Meeting`, `AgendaPacket`, `Motion`, `MinutesRecord`, `NumberSeries`, `LegislativeInstrument`, `PublicationNotice`, `CodeTitle`, `SupplementCycle`, `CodificationSubmission`, `PublicRecordsRequest`, `RecordSeries` and `DestructionBatch` all behave this way.

`AgendaItem` is the single exception. An agenda item is immutable once printed: it carries only `id` and `created_at`, and both `updated_at` and `version` are **absent** from it. There is consequently no update operation for an agenda item, and no version to quote against one.

### 2.6. Path Resolution and Referential Order

Nested paths are resolved strictly left to right. A request to a path that names a parent and a child resolves the parent first, and if the parent does not exist the request fails on the parent even when the child identifier is also unknown. The path variables the surface uses are `venue_id`, `meeting_id`, `packet_id`, `item_id`, `minutes_id`, `motion_id`, `instrument_id`, `notice_id`, `title_id`, `cycle_id`, `submission_id`, `request_id`, `series_id` and `batch_id`, and each has its own not-found code: `ERR_VENUE_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`, `ERR_AGENDA_ITEM_NOT_FOUND`, `ERR_MOTION_NOT_FOUND`, `ERR_MINUTES_NOT_FOUND`, `ERR_NUMBER_SERIES_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CODE_TITLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_SERIES_NOT_FOUND` and `ERR_BATCH_NOT_FOUND`, all HTTP 404. A path segment naming a numbering series resolves against `NumberSeries` and reports `ERR_NUMBER_SERIES_NOT_FOUND`; a path segment naming a retention series resolves against `RecordSeries` and reports `ERR_SERIES_NOT_FOUND`.

Identifiers supplied inside a request body are resolved after the path, in the order the endpoint declares its input fields, and use the same catalogue of 404 codes — so a body naming both an unknown meeting and an unknown instrument fails on whichever appears earlier in the endpoint's declared input list. The body-borne foreign keys that participate in this check are `venue_id`, `meeting_id`, `agenda_item_id`, `target_minutes_id`, `number_series_id`, `instrument_id`, `code_title_id`, `cycle_id`, `winning_submission_id`, `target_series_id` and `series_id`.

Only after every identifier resolves does the service validate request shape — required fields present, enum values inside their declared sets, numeric ranges honoured, dates well formed — reporting `ERR_INVALID_REQUEST` (HTTP 422) for any failure. That single code also covers the conditional pairings this domain requires: `scheduled_end` strictly after `scheduled_start`; `ordinance_category` absent exactly when `instrument_class` is `RESOLUTION`; `code_title_id` and `code_section_ref` both present exactly when `ordinance_category` is `CODE_AMENDMENT`; `denial_basis` present when a disposition is a denial; and `winning_submission_id` naming one of the two conflicting submissions when the resolution basis is a manual override.

### 2.7. Optimistic Concurrency on Parent Versions

Three write operations in this service can invisibly overwrite work that another editor performed after the caller last read the record. Each is therefore guarded by optimistic concurrency control against the `version` of a **parent** record, quoted by the client as a required, non-optional input field. Endpoints that do not appear in the following three rules take no version field at all, and supplying one to them is not part of their contract.

- Creating the next agenda packet revision for a meeting — `POST /clerk/meetings/{meeting_id}/agenda-packets` — requires `expected_meeting_version` carrying the client's last observed `version` of that `Meeting`. If it does not equal the meeting's current `version`, the request is rejected with `ERR_STALE_MEETING_VERSION` (HTTP 412). The operation is legitimate on its own terms — a new revision supersedes the prior posted packet and returns the meeting to `SCHEDULED` — and the version check is what stops a writer from superseding a notice state it never saw.
- Filing a codification submission — `POST /clerk/codification-submissions` — requires `expected_code_title_version` carrying the client's last observed `version` of the `CodeTitle` the submission's cycle belongs to. A mismatch with the code title's current `version` is rejected with `ERR_STALE_CODE_TITLE_VERSION` (HTTP 412). Filing can supersede a pending submission of the same instrument, and certifying any cycle rewrites the title's `section_refs`, so a writer holding a stale view of the title would be amending or superseding text it never observed.
- Opening a correction against approved minutes — `POST /clerk/minutes/{minutes_id}/corrections` — requires `expected_minutes_version` carrying the client's last observed `version` of that `MinutesRecord`. A mismatch with the record's current `version` is rejected with `ERR_STALE_MINUTES_VERSION` (HTTP 412), because a correction replaces the approved narrative outright and a second author working from a stale reading would silently discard a correction or approval that landed after that reading.

These three checks are evaluated after authentication, authorisation, existence and request-shape validation, and before any state precondition. A caller that quotes a stale version therefore learns about the stale version rather than about the state conflict that a fresh read would have revealed.

### 2.8. Segregation of Duties on Certification

Two certifications require a second pair of hands. When a certificate of destruction is signed, the acting `X-User-ID` must differ from the `proposed_by_officer_id` recorded when the batch was proposed. When a supplement cycle is certified into the code, the acting `X-User-ID` must differ from **every** `resolved_by_user_id` stamped on that cycle's submissions — one conflict resolution by the certifying editor anywhere in the cycle is enough to bar them. Either violation is reported as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and both are evaluated before the state and aggregate checks that guard those operations.

### 2.9. Arithmetic, Rounding and Money

All monetary amounts in this service are integer counts of cents and are stored in fields whose names end in `_cents`. There is no floating-point money and no fractional cent. Where a computation produces a fractional value of cents, it is rounded **half up** to a whole cent at the step the relevant calculation names, and the calculations in section 3 are explicit about *where* the rounding lands, because rounding early per line and rounding late on a sum give different answers and both patterns appear in this domain.

`column_inches` is the one decimal input the service accepts, expressed with up to two decimal places, and it must be greater than zero. Counts of members, pages, items, insertions and staff minutes are integers. Notice hours are integers, and where an hour count is scaled by a body-type multiplier the product is rounded **up** to a whole hour. Where staff time is converted into billable quarter-hours, any part of a quarter-hour is rounded **up** to a whole quarter-hour. Retention periods are whole-year additions to a calendar date; when the anchor date is 29 February and the target year has no 29 February, the result clamps to 28 February.

### 2.10. Mirrored and Derived Fields

This service holds a number of fields that are copies or aggregates of facts owned elsewhere, and the rule for all of them is the same: they are **recomputed from their sources**, never incrementally patched by the caller, and never accepted as input.

A meeting mirrors the notice arithmetic of whichever of its agenda packets is currently posted: `Meeting.notice_posted_at`, `Meeting.required_notice_hours` and `Meeting.notice_compliant` reproduce `posted_at`, `required_notice_hours` and `notice_compliant` from the packet whose `meeting_id` is that meeting and whose `status` is `POSTED`. Where no such packet exists, the first two read null and `notice_compliant` reads false. An instrument mirrors `publication_completed_on` from its publication notice. A destruction batch snapshots `eligible_through_on` from its series at the moment the batch is proposed, and the series' own `eligible_through_on` continues to move afterwards.

Aggregate counters follow the same discipline. `AgendaPacket.item_count` and `AgendaPacket.contains_public_hearing` are derived from the packet's items. `NumberSeries.next_sequence` and `minted_count` move only when a number is actually minted. `SupplementCycle.submission_count`, `client_submission_count` and `conflict_count` are derived from that cycle's submissions, and `CodeTitle.current_supplement_number` reads the `supplement_number` of the most recently certified cycle under that title, or 0 when the title has none. On a public records request, `fee_balance_cents` and `net_cash_cents` are always recomputed from the four stored counters `total_assessed_cents`, `total_waived_cents`, `total_collected_cents` and `refunded_cents`. On a retention series, `total_accessioned_count`, `active_item_count` and `destroyed_item_count` are maintained so that the first always equals the sum of the other two.

### 2.11. Order of Evaluation

Because a single request can fail several ways at once, the service evaluates checks in a fixed order and reports the first failure it finds. Authentication comes first (missing headers, then unknown role), then endpoint authorisation, then `Requester` ownership. Existence of path identifiers follows, then existence of body identifiers, then request shape, then pagination bounds on list endpoints. Optimistic-concurrency version checks come next. Only then does the service consider state: first whether the target entity is in a state from which the requested transition is declared — reported as `ERR_INVALID_MEETING_STATE`, `ERR_INVALID_PACKET_STATE`, `ERR_INVALID_MOTION_STATE`, `ERR_INVALID_MINUTES_STATE`, `ERR_INVALID_INSTRUMENT_STATE`, `ERR_INVALID_NOTICE_STATE`, `ERR_INVALID_SUBMISSION_STATE`, `ERR_INVALID_BATCH_STATE` or `ERR_INVALID_REQUEST_STATE`, all HTTP 409 — and then the cross-entity state guards, the closability check on a records request, and segregation of duties.

After that come the domain families, in this order: open-meeting and records-safety rules; aggregate caps and uniqueness; temporal window rules; fiscal rules; and finally referential and configuration consistency. Three orderings inside this scheme matter enough to be called out where they occur and are repeated here: on a reschedule, the notice-deadline check is evaluated **before** the venue-overlap check; on closing a records request, the disclosure-axis closability check is evaluated **before** the outstanding-balance check; and on proposing a destruction batch, the legal-hold and permanent-retention checks are evaluated **before** the item-count check against active custody.

## 3. Business Logic & Workflows

### 3.1. Chambers, Calendars and the Life of a Meeting

Before a body can meet, the room it meets in must be on the register. A `CityClerk` registers a chamber or meeting room with its public `name`, the `address` that will be printed on published notices, and the seated `capacity` published alongside the notice, which must be at least 1. Two further attributes govern the calendar rather than the notice. `teardown_buffer_minutes` is the number of minutes appended to the **end** of every meeting occupation of that room before another body may occupy it; it defaults to 30 minutes and may be set anywhere from 0 up to and including 240 minutes — four hours — for chambers that need to be reconfigured between bodies. `status` says whether the room may accept new occupations at all: it is `AVAILABLE` by default and may be set to `CLOSED`. The clerk may later revise a venue's `capacity`, `teardown_buffer_minutes` or `status`; each such revision advances the venue's `version`. Revising the buffer deliberately does **not** re-examine meetings that are already on the calendar, so a lengthened buffer never retroactively invalidates an existing booking.

Scheduling a meeting is where the calendar arithmetic bites. The clerk supplies the `body_type` of the governing body that will meet — `COUNCIL`, `PLANNING_COMMISSION` or `BOARD_OF_ADJUSTMENT` — the statutory `meeting_type`, which is one of `REGULAR`, `SPECIAL`, `EMERGENCY` or `WORKSHOP`, the `venue_id` of the room, the `scheduled_start` and `scheduled_end` instants in ISO 8601 UTC, and `quorum_required`, the minimum number of members that must be present to convene, which must be at least 1. The end instant must be strictly after the start instant. The meeting enters the register with `status` `SCHEDULED`, a `present_member_count` of 0, and no notice: `notice_posted_at` and `required_notice_hours` are null and `notice_compliant` is false.

The room's occupation is the half-open interval from `scheduled_start` up to but not including `scheduled_end`, **extended at the end by the venue's `teardown_buffer_minutes`**. That extended interval must not overlap the extended interval of any other meeting on the same venue whose `status` is `SCHEDULED`, `NOTICED` or `IN_SESSION`; an overlap is rejected with `ERR_VENUE_WINDOW_CONFLICT` (HTTP 409). Meetings that have already `ADJOURNED` or been `CANCELLED` release their claim on the room entirely. Independently, a room whose `status` is `CLOSED` accepts no bookings at all, and an attempt to book one is rejected with `ERR_VENUE_CLOSED` (HTTP 409). Both checks apply again, unchanged, when the clerk moves an existing meeting to a new window by supplying a fresh `scheduled_start` and `scheduled_end`; a move advances the meeting's `version`.

Moving a meeting that has already been noticed carries a second obligation. If a posted packet exists, the move recomputes that packet's notice arithmetic against the new start instant and re-mirrors `required_notice_hours` and `notice_compliant` onto the meeting; and if the recomputed deadline would fall at or before the logical clock — meaning the new date leaves less notice than the statute demands, counted from now — the move is refused with `ERR_NOTICE_DEADLINE_MISSED` (HTTP 409). On a reschedule this notice check runs **before** the venue-overlap check, so a move that both shortens the notice and double-books the room reports the notice failure.

Cancellation is available from either `SCHEDULED` or `NOTICED` and requires a `cancelled_reason`, which is recorded on the meeting and appears on the cancellation notice; the reason is null on any meeting that has not been cancelled. Cancelling drives the meeting to `CANCELLED` and fans out: every agenda packet of that meeting whose `status` is `DRAFT` or `POSTED` moves to `WITHDRAWN`; every meeting-agenda publication notice of that meeting whose `status` is `DRAFT` or `ORDERED` moves to `VOID`; and a fresh publication notice of type `CANCELLATION` is created in `DRAFT` against that meeting. When the cancelled meeting was in `NOTICED`, the cancellation additionally clears the mirrored notice state, setting `notice_posted_at` back to null and `notice_compliant` back to false. `ADJOURNED` and `CANCELLED` are terminal for a meeting; an attempt to cancel a meeting that is `IN_SESSION`, already adjourned or already cancelled is an invalid meeting state.

Meetings can be read one at a time, or listed with optional `venue_id` and `status` filters, by any of the five staff roles.

### 3.2. Agenda Packets, Items and the Open-Meeting Notice Clock

The agenda packet is the instrument that notices a meeting, and it exists in revisions. A `CityClerk` creates the next revision for a meeting by quoting `expected_meeting_version` and, optionally, `late_addendum` — a flag, false by default, marking a packet that carries an item added after the original notice went out. The new packet's `revision_number` is 1 plus the highest `revision_number` among the packets already filed for that meeting, and it enters in `DRAFT` with `item_count` 0, `contains_public_hearing` false, `notice_compliant` false and `posted_at` null. Creating a revision supersedes what came before: every prior packet of the meeting still in `DRAFT` or `POSTED` moves to `SUPERSEDED`, and if the superseded packet was the posted one, the meeting travels `NOTICED → SCHEDULED` and its mirrored notice fields are cleared — the packet-revision loop that lets a clerk re-notice a meeting with a corrected agenda. Either way the meeting's `version` advances, which is exactly why the operation is version-guarded. A meeting tolerates at most three packet revisions; an attempt to create a fourth is rejected with `ERR_PACKET_REVISION_LIMIT` (HTTP 422).

Items are added to a packet only while it is in `DRAFT`, by a `CityClerk` or a `DeputyClerk`, each with a `sequence_number` giving its printed order within the packet, an `item_type`, and a `title` that is the caption printed on the agenda. `sequence_number` must be at least 1 and must be unique within its packet; a collision is `ERR_DUPLICATE_SEQUENCE_NUMBER` (HTTP 422). `item_type` is one of `CONSENT`, `PUBLIC_HEARING`, `ORDINANCE_FIRST_READING`, `ORDINANCE_ADOPTION`, `RESOLUTION`, `MINUTES` or `REPORT`. Each addition advances the packet's `item_count` by 1, and adding an item of type `PUBLIC_HEARING` turns `contains_public_hearing` true. An item, once added, is a printed artefact and is never edited or removed; items are read individually or listed either within their packet — in `sequence_number` order — or across packets with optional `packet_id` and `item_type` filters.

How much notice the meeting owes the public is a function of what the packet contains and which body is meeting. The base requirement comes from the statutory meeting class: a `REGULAR` meeting owes 72 hours — three full days — while `SPECIAL` and `WORKSHOP` meetings each owe 48 hours and an `EMERGENCY` meeting owes only 24 hours. To that base, two additions apply. If the packet contains at least one public-hearing item, a further 168 hours — a full week — is added. If the packet is flagged as a late addendum, a further 24 hours is added. The three components are summed first, and the sum is then multiplied by a multiplier keyed on the governing body: 1.0 for `COUNCIL`, and 1.5 for both `PLANNING_COMMISSION` and `BOARD_OF_ADJUSTMENT`. That product is rounded **up** to a whole number of hours to give `required_notice_hours`, and the rounding-up happens before, never after, the next step. `notice_deadline_at` is then the meeting's `scheduled_start` minus `required_notice_hours` hours. Both values are computed when the packet is created and stored on it.

Posting is the act that notices the meeting, and it recomputes before it commits. Because public-hearing items may have been added to the packet after it was created, a `CityClerk` posting a packet causes `required_notice_hours` and `notice_deadline_at` to be recalculated from the packet's items **as they stand at that moment**, by the same arithmetic. The logical clock instant is then stored as `posted_at`, and `notice_compliant` is set to true when `posted_at` falls at or before `notice_deadline_at` and false otherwise — posting at exactly the deadline instant is compliant, comparison being at second granularity. The packet travels `DRAFT → POSTED`, the meeting travels `SCHEDULED → NOTICED`, the meeting's `version` advances, and `notice_posted_at`, `required_notice_hours` and `notice_compliant` are mirrored from the packet onto the meeting.

Posting late is not an error. A packet that misses its deadline still posts, still notices the meeting, and still answers 200 — it simply records `notice_compliant` as false, and the consequence surfaces later, when the meeting cannot be called to order and when a reschedule is refused. Posting is only available from `DRAFT`, requires the meeting to still be in `SCHEDULED`, and requires the packet to carry at least one item: posting a packet whose `item_count` is 0 is rejected with `ERR_EMPTY_AGENDA_PACKET` (HTTP 422). Posting also creates the publication paperwork: a publication notice of type `MEETING_AGENDA` is created in `DRAFT` against the meeting, carrying the insertion count and publication deadline described in section 3.6.

Withdrawal reverses a posting. A packet in `DRAFT` or `POSTED` may be withdrawn by a `CityClerk`, which drives it to `WITHDRAWN`. Withdrawing a packet that was merely `DRAFT` touches nothing else — a draft packet never noticed anything. Withdrawing the packet that was `POSTED` returns the meeting `NOTICED → SCHEDULED`, sets `notice_posted_at` and `required_notice_hours` back to null and `notice_compliant` back to false, advances the meeting's `version`, and voids that meeting's `MEETING_AGENDA` publication notice if it sits in `DRAFT` or `ORDERED`. `SUPERSEDED` and `WITHDRAWN` are both terminal for a packet.

Packets are read individually, listed per meeting, or listed across meetings with optional `meeting_id` and `status` filters.

### 3.3. Calling the Meeting to Order, Motions and the Vote Arithmetic

Only a `PresidingOfficer` may call a meeting to order, and only from `NOTICED`. Two conditions gate the transition `NOTICED → IN_SESSION`. First, the meeting's mirrored `notice_compliant` must be true; if the posted packet missed its statutory deadline, the meeting cannot lawfully convene and the attempt is refused with `ERR_NOTICE_DEADLINE_MISSED` (HTTP 409). Second, the `present_member_count` supplied with the call must be at least the meeting's `quorum_required`; a short house is refused with `ERR_QUORUM_NOT_MET` (HTTP 409). The notice check is evaluated before the quorum check, so a meeting that is both non-compliant and short of quorum reports the notice failure. On success the supplied count is stored as the meeting's `present_member_count`, and that stored number — not the count on any later request — is the denominator every vote at this meeting is measured against.

A motion enters the register already moved and seconded; an unseconded motion is never recorded at all. A `CityClerk` or `DeputyClerk` records one against the `meeting_id` of a meeting that must be `IN_SESSION` — recording against a meeting in any other state is `ERR_MEETING_NOT_IN_SESSION` (HTTP 409) — supplying the `motion_type`, the `majority_rule` that will be applied, the opaque `moved_by_member_id` of the mover and the opaque `seconded_by_member_id` of the seconder, which is required at creation. Optionally the motion names the `agenda_item_id` of the agenda item it was moved under. The motion enters with `status` `SECONDED`, `outcome` `PENDING`, `result_official` false and all four vote counters at 0.

What a motion targets depends on what it does. `motion_type` is one of `ORDINANCE_ADOPTION`, `RESOLUTION_ADOPTION`, `MINUTES_APPROVAL`, `MINUTES_CORRECTION`, `VETO_OVERRIDE` or `PROCEDURAL`. An `ORDINANCE_ADOPTION`, `RESOLUTION_ADOPTION` or `VETO_OVERRIDE` motion must carry `instrument_id` naming the legislative instrument it acts on, and must leave `target_minutes_id` null. A `MINUTES_APPROVAL` or `MINUTES_CORRECTION` motion must carry `target_minutes_id` naming the minutes record it acts on, must leave `instrument_id` null, and — because a body cannot approve the minutes of the meeting it is currently holding — the named minutes must belong to a **different** meeting than the motion's own. A `PROCEDURAL` motion carries neither. Any breach of this pairing, including a minutes motion aimed at the current meeting's own minutes, is rejected with `ERR_MOTION_TARGET_INVALID` (HTTP 422).

Tallying is reserved to the `CityClerk` and is available only from `SECONDED`, and only while the motion's meeting is still `IN_SESSION`. The clerk supplies `yes_count`, `no_count`, `abstain_count` and `recused_count`, and optionally `presiding_tie_break`, which is either `YES` or `NO`. Two arithmetic gates come first. The four counts must together account for exactly the meeting's `present_member_count`; any other sum is `ERR_VOTE_TALLY_MISMATCH` (HTTP 422). And at least one present member must remain unrecused: if `recused_count` equals `present_member_count`, so that nobody is eligible to vote, the tally is refused with `ERR_NO_VOTING_MEMBERS` (HTTP 422).

The arithmetic itself is deliberately unforgiving about abstentions. `effective_base` is the meeting's `present_member_count` less `recused_count` — recusals leave the base, abstentions stay in it. That means an abstention counts against the motion in effect, since it enlarges the denominator without ever contributing an aye. `required_yes` is then derived from `majority_rule` on that base: under `SIMPLE` it is half the base discarding any remainder, plus one; under `TWO_THIRDS` it is two thirds of the base rounded up to a whole member; under `FOUR_FIFTHS` it is four fifths of the base rounded up to a whole member; and under `UNANIMOUS_CONSENT` it is the whole base. All of this is integer arithmetic.

The `outcome` follows in three branches. If `yes_count` is at least `required_yes`, the outcome is `PASSED`. Otherwise, if the ayes exactly equal the nays, the rule in force is `SIMPLE`, and a `presiding_tie_break` was supplied, the presiding officer's vote decides: the outcome is `TIE_BROKEN_PASSED` when the tie-break is `YES` and `TIE_BROKEN_FAILED` when it is `NO`, and `tie_break_used` is set true. In every other case the outcome is `FAILED`. The tie-break branch is reachable **only** under `SIMPLE` and **only** on an exact tie — a tie under `TWO_THIRDS`, `FOUR_FIFTHS` or `UNANIMOUS_CONSENT` simply fails, and a tie-break value supplied where the branch is unreachable is ignored and leaves `tie_break_used` false. The motion moves `SECONDED → TALLIED`, and `effective_base`, `required_yes`, `outcome` and `tie_break_used` are all recorded on it.

A tallied motion then acts on whatever it targeted, and this is where the vote reaches out of its own aggregate. A passing `ORDINANCE_ADOPTION` moves its instrument `FIRST_READING_PASSED → ADOPTED_UNOFFICIAL` and stamps the logical clock date onto `voted_on`; a failing one moves the instrument `FIRST_READING_PASSED → FAILED`, and no number is ever minted for it. A passing `RESOLUTION_ADOPTION` moves its instrument `INTRODUCED → ADOPTED_UNOFFICIAL` with `voted_on` stamped the same way. A passing `MINUTES_APPROVAL` moves its target minutes `SUBMITTED → APPROVED` and is the head of the officialization cascade described in section 3.4. A `MINUTES_CORRECTION` returns its target minutes `CORRECTION_PENDING → APPROVED` whichever way it goes, adopting or discarding the pending text according to the outcome. A passing `VETO_OVERRIDE` moves its instrument `VETOED → VETO_OVERRIDDEN`. A `PROCEDURAL` motion records its outcome and nothing more. Both `TALLIED` and `WITHDRAWN` are terminal for a motion, so a motion is tallied at most once; a second tally attempt is an invalid motion state.

Adjournment closes the sitting. Only a `PresidingOfficer` may adjourn, and only from `IN_SESSION`. The meeting moves to `ADJOURNED`, `adjourned_at` records the logical clock instant, a fresh minutes record is opened in `DRAFT` against the meeting with `revision_number` 1 and an empty `text_body`, and every motion of that meeting still sitting in `SECONDED` is swept to `WITHDRAWN` — its `outcome` staying `PENDING`, and no instrument or minutes touched by the sweep. Motions already `TALLIED` are left exactly as they are; this is a conditional sweep, not a blanket one. The same sweep of un-tallied motions applies when a meeting is cancelled.

Motions can be read individually or listed with optional `meeting_id`, `agenda_item_id`, `instrument_id`, `target_minutes_id` and `status` filters, which is how a clerk finds every motion whose result is still unofficial.

### 3.4. Minutes: Drafting, Approval and the Correction Cycle

A minutes record comes into existence only at adjournment, one per meeting, and it is the artefact that turns a recorded vote into an official act. It carries the `meeting_id` of the meeting it records, a `revision_number` that starts at 1, a `text_body` that starts empty, a `correction_count` that starts at 0, and a `status` that starts at `DRAFT`. `pending_correction_text` and `approved_on` are null at the outset.

While the record is in `DRAFT`, a `CityClerk` or `DeputyClerk` writes the official narrative into `text_body`; each write advances the record's `version`. A `CityClerk` then submits it, moving `DRAFT → SUBMITTED` and advancing `version` again. Submission has two preconditions: the narrative must not be empty, and the parent meeting must already be `ADJOURNED`. Attempting to write or submit a record that is not in `DRAFT` is `ERR_INVALID_MINUTES_STATE` (HTTP 409).

Approval never happens at the meeting the minutes describe. A submitted record reaches `APPROVED` only as the consequence of a passing `MINUTES_APPROVAL` motion tallied at a *later* meeting — one whose own `meeting_id` differs from the minutes' `meeting_id` — and whose `target_minutes_id` names the record. When that tally lands, `approved_on` is stamped with the logical clock date, and the cascade begins.

**Hop 1** is the minutes transition itself, `SUBMITTED → APPROVED`. **Hop 2** flips `result_official` to true on *every* motion whose `meeting_id` is the approved minutes' `meeting_id` — not merely the adoption motions, and not merely the passing ones, because the whole record of that sitting becomes official at once. **Hop 3** reads that flip: each such motion whose `motion_type` is `ORDINANCE_ADOPTION` or `RESOLUTION_ADOPTION` and whose `outcome` is `PASSED` or `TIE_BROKEN_PASSED` moves its instrument `ADOPTED_UNOFFICIAL → ADOPTED`, stamps `adoption_date` with the logical clock date, and mints the instrument's `assigned_number` from its numbering series as described in section 3.5. **Hop 4** is the consequence of adoption: an ordinance acquires a draft publication notice, while a resolution — which is never published — takes its effective date immediately and goes straight on to `EFFECTIVE`. Sections 3.5 and 3.6 give hops 3 and 4 in full.

Approved minutes can still be wrong, and correcting them is a cycle rather than a one-way door. A `CityClerk` or `DeputyClerk` opens a correction against an `APPROVED` record by quoting `expected_minutes_version` and supplying `corrected_text_body`. The record moves `APPROVED → CORRECTION_PENDING`, the proposed replacement narrative is parked in `pending_correction_text`, `correction_count` advances by 1 — counting every correction ever opened against the record, including ones the body later refuses — and the record's `version` advances. A correction may only be opened from `APPROVED`; a record already sitting in `CORRECTION_PENDING` accepts no second correction.

The parked text is adopted or discarded by a `MINUTES_CORRECTION` motion at a subsequent meeting, and the two branches differ in exactly one respect. On a **passing** tally, `text_body` is replaced by `pending_correction_text` and `revision_number` advances by 1. On a **failing** tally, `text_body` is left untouched and `revision_number` is left untouched. In **both** branches the record returns `CORRECTION_PENDING → APPROVED`, `pending_correction_text` is cleared back to null, and `approved_on` is re-stamped with the logical clock date. This closes the loop `APPROVED → CORRECTION_PENDING → APPROVED`, and the loop may be travelled any number of times; a minutes record has no terminal state.

Minutes are read individually, listed per meeting — zero records before adjournment, one afterwards — or listed across meetings with optional `meeting_id` and `status` filters.

### 3.5. Numbering Series and the Life of a Legislative Instrument

Ordinances and resolutions are numbered out of annual series, and the series must exist before the instrument does. A `CityClerk` opens one by declaring the `series_year` it numbers, the `instrument_class` it serves — either `ORDINANCE` or `RESOLUTION` — and the alphabetic `prefix` that will be printed in the numbers it mints, such as `ORD` for ordinances. The clerk may optionally supply `next_sequence` to start the series at a number other than 1; left unset it starts at 1. `minted_count` starts at 0 and counts the instruments that have drawn a number from the series, and `status` starts at `OPEN`. Only one series may exist for a given combination of `series_year` and `instrument_class`; a duplicate is refused with `ERR_DUPLICATE_NUMBER_SERIES` (HTTP 422). A clerk may later close a series, moving `status` `OPEN → CLOSED`, after which nothing may draw a number from it.

Introducing an instrument is a `CityClerk` act. The clerk declares the `instrument_class`, the long `title` as introduced, the `full_text_length` — the character length of the enacted text, which must be at least 1 and which later decides whether the ordinance is published in full or in summary — and the `number_series_id` of the series the instrument will draw from. `ordinance_category` is required for an ordinance and must be one of `GENERAL`, `ZONING`, `CODE_AMENDMENT` or `EMERGENCY`; it must be null for a resolution. When and only when the category is `CODE_AMENDMENT`, the clerk must also supply `code_title_id` naming the municipal code title the ordinance touches and `code_section_ref` naming the section, written in the customary dotted form such as `12.04.030`; for every other category both are null.

Two consistency checks guard the introduction. The chosen series' `instrument_class` must match the instrument's own, and the series' `series_year` must equal the calendar year of the logical clock date at introduction — a 2026 ordinance cannot be numbered out of the 2025 book, and an ordinance cannot be numbered out of a resolution series; either mismatch is `ERR_SERIES_CLASS_MISMATCH` (HTTP 422). The series must also be `OPEN`; introducing against a closed series is `ERR_NUMBER_SERIES_CLOSED` (HTTP 409). The instrument enters at `status` `INTRODUCED` with `reading_count` 0, `assigned_number` null, `voted_on`, `adoption_date`, `publication_completed_on`, `effective_date_basis`, `effective_date` and `veto_reason` all null, and `requires_publication` set true for an `ORDINANCE` and false for a `RESOLUTION`.

Ordinances take a reading before they can be adopted. A `CityClerk` records the reading against the `meeting_id` of a meeting that must be `IN_SESSION` — otherwise `ERR_MEETING_NOT_IN_SESSION` — moving the instrument `INTRODUCED → FIRST_READING_PASSED` and advancing `reading_count` by 1. Only an ordinance takes a reading; a resolution goes to the floor directly from `INTRODUCED`. From there, adoption is the work of a motion (section 3.3): an ordinance is adopted out of `FIRST_READING_PASSED` and a resolution out of `INTRODUCED`, and in both cases the tally leaves the instrument in `ADOPTED_UNOFFICIAL` — voted, recorded, but not yet official, because the minutes carrying the vote have not been approved.

Numbering happens at the moment the vote becomes official, not when it is cast. When the officialization cascade of section 3.4 moves an instrument `ADOPTED_UNOFFICIAL → ADOPTED`, the server stamps `adoption_date` with the logical clock date and mints `assigned_number` by joining the series' `prefix`, the series' `series_year` and the series' current `next_sequence` zero-padded to three digits, separated by hyphens — so a series with prefix `ORD` for 2026 standing at sequence 7 mints `ORD-2026-007`. The series then advances: `next_sequence` by 1 and `minted_count` by 1. Two conditions can stop the mint. If the series has been closed in the meantime, the cascade fails with `ERR_NUMBER_SERIES_CLOSED`; and no sequence above 999 may be minted, so a series standing beyond that limit fails with `ERR_NUMBER_SERIES_EXHAUSTED` (HTTP 422). A failing adoption motion mints nothing and leaves `assigned_number` null forever, the instrument resting in the terminal state `FAILED`.

An adopted ordinance may be vetoed. Only a `PresidingOfficer` may do so, only from `ADOPTED`, and only against an ordinance — a resolution is never vetoable. The officer supplies `veto_reason`, which is recorded on the instrument and is null on any instrument that was never vetoed; the instrument moves `ADOPTED → VETOED` and its publication notice, if one is sitting in `DRAFT` or `ORDERED`, is voided. A veto is not the end: a `VETO_OVERRIDE` motion carrying that instrument's `instrument_id`, tallied under the `FOUR_FIFTHS` rule and passing, moves the instrument `VETOED → VETO_OVERRIDDEN` and causes a **replacement** publication notice to be created in `DRAFT`, since the original was voided. The four-fifths rule is a precondition of the override, not merely a convention: an override motion tallied under any other `majority_rule` does not move the instrument out of `VETOED`.

Where the effective date comes from depends on what kind of instrument it is, and the service records that choice explicitly in `effective_date_basis` alongside the `effective_date` itself. The basis is selected by working down this list and taking the first match: a `RESOLUTION` takes `ADOPTION_IMMEDIATE`; an ordinance whose `ordinance_category` is `EMERGENCY` takes `ADOPTION_IMMEDIATE`; an ordinance whose category is `CODE_AMENDMENT` takes `SUPPLEMENT_CERTIFIED`; anything else — that is, a `GENERAL` or `ZONING` ordinance — takes `PUBLICATION_PLUS_30`.

The arithmetic then differs by basis. Under `ADOPTION_IMMEDIATE` the `effective_date` is simply the `adoption_date`, with no lag and no weekend adjustment of any kind; a resolution therefore becomes `EFFECTIVE` in the same cascade that adopts it, and an emergency ordinance takes effect the day it was made official. The other two bases start from a common intermediate: take `publication_completed_on`, add 30 days, and then roll the result forward off the weekend — if that date falls on a Saturday add 2 days, if it falls on a Sunday add 1 day, and otherwise leave it alone. The roll is applied **after** the thirty-day addition and never before it. Under `PUBLICATION_PLUS_30` the rolled date is the `effective_date`. Under `SUPPLEMENT_CERTIFIED` the `effective_date` is the **later** of that rolled date and the `certified_on` date of the supplement cycle carrying the instrument's accepted codification submission; while that cycle remains uncertified there is no date at all and `effective_date` stays null. All of this is calendar-date arithmetic in UTC.

An instrument reaching `EFFECTIVE` or `FAILED` is at rest; those two are its terminal states. Instruments are read individually, exposing `assigned_number`, `effective_date_basis` and `effective_date`, or listed with optional `number_series_id`, `code_title_id` and `status` filters.

### 3.6. Newspaper Publication: Requirement, Invoice and Certification

Nobody creates a publication notice directly. Notices appear as consequences: posting an agenda packet raises a `MEETING_AGENDA` notice, cancelling a meeting raises a `CANCELLATION` notice, and an ordinance becoming official — or an override reviving one after a veto — raises an ordinance notice. Each is created in `DRAFT` with `newspaper_name`, `column_inches`, `publication_dates` and `publication_completed_on` all null, and each carries either an `instrument_id` or a `meeting_id`: an ordinance notice carries `instrument_id` and no `meeting_id`, while a `MEETING_AGENDA` or `CANCELLATION` notice carries `meeting_id` and no `instrument_id`.

Which kind of ordinance notice is raised, and how many insertions it owes, is decided from the ordinance's own text length — and the direction is the opposite of what intuition suggests. An ordinance whose `full_text_length` is **greater than** 4,000 characters is too long to print entire, so it takes `notice_type` `ORDINANCE_SUMMARY` and owes a single insertion. An ordinance of 4,000 characters or fewer takes `ORDINANCE_FULL_TEXT` and owes **two** insertions. A long ordinance therefore needs fewer publications than a short one. `MEETING_AGENDA` and `CANCELLATION` notices each owe one insertion. That count is stored as `required_publication_count`.

The `publication_deadline_on` is the latest calendar date any required insertion may bear, and it too depends on what is being published. For an ordinance notice it is the instrument's `adoption_date` plus 15 days. For a `MEETING_AGENDA` notice it is the calendar date of the meeting's `scheduled_start` minus one day — the agenda must be in the paper before the day of the meeting. For a `CANCELLATION` notice it is the calendar date of the meeting's `scheduled_start` itself, since a cancellation is still useful on the morning of the meeting it cancels.

Placing the insertion order is available to a `CityClerk` or `DeputyClerk` and only from `DRAFT`. The caller names the `newspaper_name` — the newspaper of record — supplies `column_inches`, the billed column inches per insertion as a decimal greater than zero, supplies `publication_dates` as the list of ISO dates the insertions will bear, and declares `affidavit_required`, a flag saying whether a publisher's affidavit is being purchased for each insertion. Three scheduling rules apply to the supplied dates. The number of dates must equal the notice's `required_publication_count`, or the order is refused with `ERR_PUBLICATION_COUNT_MISMATCH` (HTTP 409). The latest of the dates must fall on or before `publication_deadline_on`, or the order is refused with `ERR_PUBLICATION_DEADLINE_MISSED` (HTTP 409). And the dates must be strictly increasing with each consecutive pair separated by at least 7 days — a full week between insertions — or the order is refused with `ERR_PUBLICATION_INTERVAL_TOO_SHORT` (HTTP 409). A successful order moves the notice `DRAFT → ORDERED` and stores the newspaper, the column inches and the dates.

The order is also the moment the invoice is priced, and the sequence of the arithmetic matters more than any single rate in it. First the per-insertion charge is computed: `column_inches` is multiplied by 500 cents — five dollars per column inch — and that product is rounded half up to a whole cent **per insertion**, before anything is multiplied out. `gross_cost_cents` is then that per-insertion figure multiplied by the number of insertions ordered, and the affidavit is deliberately **excluded** from it. `discount_pct` is a volume discount keyed on `gross_cost_cents`: a gross below 50,000 cents earns no discount at all; a gross from 50,000 cents up to but not including 150,000 cents earns 0.05; and a gross of 150,000 cents or more earns 0.10. The discounted figure is the gross multiplied by one minus the discount fraction, again rounded half up to a whole cent. Only then is the affidavit added: 2,500 cents per insertion when `affidavit_required` is true and nothing when it is false, added **after** the discount rather than before it. The sum is `invoice_total_cents`. Because the tier is keyed on a gross that excludes the affidavit, buying affidavits can never purchase a better discount tier; and because the tier boundary is a step rather than a slope, a slightly *smaller* advertisement whose gross falls just under a boundary can bill *more* than a slightly larger one whose gross clears it. That inversion is intended and must not be smoothed away.

Certifying publication is reserved to the `CityClerk` and is available only from `ORDERED`. The clerk supplies `publication_completed_on`, which must equal the **latest** date in the notice's `publication_dates` — the certificate attests that the last ordered insertion actually ran. The notice moves `ORDERED → PUBLISHED` and stores the date. This is **hop 1** of the publication-to-codification cascade.

For an ordinance notice, **hop 2** follows immediately: the instrument mirrors `publication_completed_on` from the notice, its `effective_date_basis` and `effective_date` are computed by the rules in section 3.5, and the instrument moves `ADOPTED → PUBLISHED` or, when it had been revived by an override, `VETO_OVERRIDDEN → PUBLISHED`. From there the two categories part ways. For an ordinance that is **not** a `CODE_AMENDMENT`, the instrument goes straight on `PUBLISHED → EFFECTIVE` in the same request if and only if the computed `effective_date` is already at or before the logical clock date; if the effective date is still in the future, the instrument simply remains `PUBLISHED`. For a `CODE_AMENDMENT` ordinance, **hop 3** instead enrols it into codification: a codification submission is created automatically, with `origin` `CASCADE`, `action` `AMEND`, `status` `PENDING`, the instrument's own `code_section_ref`, and the `cycle_id` of the cycle selected as follows — among supplement cycles whose `status` is `OPEN` and whose `code_title_id` equals the instrument's `code_title_id` and whose inclusive window contains the logical clock date, take the one with the earliest `window_close_on`, breaking a tie by the earliest `created_at`. If no cycle qualifies, the whole certification fails with `ERR_NO_OPEN_SUPPLEMENT_CYCLE` (HTTP 409). **Hop 4** then advances that cycle's `submission_count` by 1 and applies the conflict rule of section 3.7 — if another submission in the cycle already holds the same `code_section_ref` for a **different** instrument, both rows are put into `CONFLICT_HELD`.

A `MEETING_AGENDA` or `CANCELLATION` notice cascades nowhere; certifying it publishes the notice and stops. Notices that are voided by a meeting cancellation, a packet withdrawal or an instrument veto move to `VOID` from either `DRAFT` or `ORDERED`, and they **retain** `publication_dates`, `gross_cost_cents`, `discount_pct` and `invoice_total_cents` for audit — the city may still owe the newspaper for an insertion it has already placed. `PUBLISHED` and `VOID` are terminal for a notice. Notices are read individually, exposing the invoice arithmetic, or listed with optional `instrument_id`, `meeting_id` and `status` filters.

### 3.7. Codification: Supplement Cycles, Submissions and Old-Versus-New Conflicts

The municipal code is organised into titles, and a title is the unit a supplement is certified against. A `CodificationEditor` creates one with its `title_number`, which must be at least 1 and unique across the code — a duplicate is `ERR_DUPLICATE_CODE_TITLE` (HTTP 422) — and its `name`, the caption such as `Zoning`. `status` is optional at creation and says whether the title accepts codification work: `ACTIVE` by default, or `RESERVED` for a title number held open for future use. A new title starts with an empty `section_refs` list and a `current_supplement_number` of 0. `section_refs` holds the section references currently in force under the title and is the referential authority the pipeline consults: an `AMEND` or a `REPEAL` may only be filed against a section that already appears there, while an `ADD` introduces one that does not.

Codification work is batched into supplement cycles, each occupying a submission window on one title. The editor opens a cycle with its `supplement_number` — at least 1, and unique within its title, a duplicate being `ERR_DUPLICATE_SUPPLEMENT_NUMBER` (HTTP 422) — and the inclusive date interval from `window_open_on` to `window_close_on`, the first and last dates on which submissions may be filed. The closing date must not precede the opening date. Windows on the same title may not collide, and the collision rule is strict: a new window may neither overlap **nor abut** any existing cycle on that title whose `status` is `OPEN` or `LOCKED`, so a window opening the very day after another closes is still refused with `ERR_SUPPLEMENT_WINDOW_CONFLICT` (HTTP 409). Cycles that have already been `CERTIFIED` impose no such constraint. A cycle enters at `status` `OPEN` with `submission_count`, `client_submission_count` and `conflict_count` all 0 and `certified_on` null.

A submission is the request to carry one ordinance's text into one code section. A `CodificationEditor` files one by naming the `cycle_id` it goes into, the `instrument_id` of the adopted instrument whose text is being codified, the `code_section_ref` the submission touches, the `action` — `ADD`, `AMEND` or `REPEAL` — and `expected_code_title_version`. The submission is stamped with `origin` `CLIENT`, enters at `status` `PENDING`, and advances both the cycle's `submission_count` and its `client_submission_count` by 1; the code title's `version` advances too, which is why the filing is version-guarded. Four gates apply. The cycle must be `OPEN`, or the filing is `ERR_CYCLE_NOT_OPEN` (HTTP 409). The logical clock date must fall inside the cycle's inclusive window, boundaries included, or the filing is `ERR_OUTSIDE_SUBMISSION_WINDOW` (HTTP 409). At most three client-origin submissions may sit in one cycle, counting everything except rows that have been withdrawn; a fourth is `ERR_CYCLE_SUBMISSION_CAPACITY` (HTTP 422). And the references must line up: the submission's `code_section_ref` must equal the instrument's own `code_section_ref`, and the instrument's `code_title_id` must equal the cycle's `code_title_id`, or the filing is `ERR_CODE_SECTION_UNKNOWN` (HTTP 422).

Submissions raised by the publication cascade of section 3.6 are stamped `origin` `CASCADE` instead, and they are **exempt from the three-submission cap** — the city's own automatic enrolment of a published code amendment can never be squeezed out by client filings. They too advance `submission_count`, but not `client_submission_count`.

Two things can happen to an existing row when a new submission lands on the same section. If the incoming submission carries the **same** `instrument_id` and the **same** `code_section_ref` as an existing `PENDING` row in the same cycle, that older row is a superseded draft: it moves `PENDING → WITHDRAWN`, and the counters are decremented for it and incremented for the newcomer, so `submission_count` and `client_submission_count` end where they started. If the incoming submission collides on `code_section_ref` with a row of a **different** `instrument_id` whose `status` is `PENDING` or `IN_REVIEW`, that is a genuine old-versus-new provision conflict: **both** rows move to `CONFLICT_HELD`, each row's `conflict_with_submission_id` is pointed at the other, and the cycle's `conflict_count` advances by 1. Because a conflict always holds two rows, `conflict_count` is always the number of `CONFLICT_HELD` submissions in the cycle divided by two, and `conflict_with_submission_id` is non-null exactly while a row sits in `CONFLICT_HELD`.

Locking the cycle closes it to new filings. The editor may lock only from `OPEN` and only when the cycle holds at least one submission; the cycle moves `OPEN → LOCKED` and every submission of that cycle sitting in `PENDING` moves to `IN_REVIEW`. Rows already in `CONFLICT_HELD` are deliberately untouched by the sweep — they are not reviewable until their conflict has been resolved. From a locked cycle the editor decides each reviewable submission by supplying a `decision` of either `ACCEPT` or `REJECT`, moving it `IN_REVIEW → ACCEPTED` or `IN_REVIEW → REJECTED`. Deciding is available only from `IN_REVIEW` and only while the parent cycle is `LOCKED`; a cycle in the wrong state reports `ERR_CYCLE_NOT_LOCKED` (HTTP 409) and a submission in the wrong state reports `ERR_INVALID_SUBMISSION_STATE`.

Resolving a conflict is the negotiation at the heart of codification, and the answer depends on which rule the editor invokes. The editor supplies a `resolution_basis` and, for a manual override, a `winning_submission_id`. Under `LATER_ADOPTION_WINS` the two partners are ranked by their instruments' `adoption_date`, latest first; a tie is broken by the sequence component of the instruments' `assigned_number`, highest first; and a remaining tie is broken by the submissions' `created_at`, earliest first — never by comparing the submission identifiers. Under `SPECIFIC_OVER_GENERAL` the ranking is by how specific the instrument's `ordinance_category` is, most specific first, where `ZONING` ranks above `CODE_AMENDMENT`, which ranks above `GENERAL`, which ranks above `EMERGENCY`; a tie is broken by later `adoption_date` first and then by earlier `created_at`. Under `MANUAL_OVERRIDE` the winner is simply the submission named by `winning_submission_id`, which must be one of the two partners — anything else is `ERR_INVALID_REQUEST`. The two named bases can select **opposite** winners on the same pair, which is precisely why the chosen rule is recorded rather than merely applied.

Whichever basis is used, the resolution is symmetric and settles both rows in one request. The winner moves `CONFLICT_HELD → ACCEPTED` and the loser moves `CONFLICT_HELD → REJECTED`; `conflict_with_submission_id` is cleared to null on both; `resolution_basis` and `resolved_by_user_id` — the acting `X-User-ID` — are stamped on both; and the cycle's `conflict_count` retreats by 1. The response body is the submission named in the path, whichever side of the conflict it turned out to be on. Resolution is available only from `CONFLICT_HELD` and only inside a `LOCKED` cycle. `ACCEPTED`, `REJECTED` and `WITHDRAWN` are terminal for a submission.

Certification carries the supplement into the code, and it is the most heavily guarded operation in this section. The editor supplies `certified_on`, the date printed on the certificate to the codifier. The cycle must be `LOCKED`. Its `conflict_count` must be 0 and no submission may still be sitting in `CONFLICT_HELD`, or the attempt is `ERR_UNRESOLVED_CONFLICTS` (HTTP 409); no submission may still be `PENDING` or `IN_REVIEW`, or the attempt is `ERR_CYCLE_HAS_OPEN_SUBMISSIONS` (HTTP 409); and the acting `X-User-ID` must differ from every `resolved_by_user_id` recorded on the cycle's submissions, or the attempt is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

On success the cycle moves `LOCKED → CERTIFIED`, which is terminal, and `certified_on` is stored. The accepted submissions then rewrite the title: an `ADD` appends its `code_section_ref` to the title's `section_refs`, a `REPEAL` removes it, and an `AMEND` leaves the list unchanged because the section is already there and only its text has moved. The title's `current_supplement_number` is set to the cycle's `supplement_number` and the title's `version` advances by 1. Finally, each accepted submission's instrument moves `PUBLISHED → EFFECTIVE`, its `effective_date` recomputed under the `SUPPLEMENT_CERTIFIED` basis — the later of the rolled thirty-day date and this cycle's `certified_on` — which is why a code amendment's effective date could not be settled before this moment.

Cycles are read individually, exposing `submission_count`, `client_submission_count` and `conflict_count`, listed per title, or listed across titles with optional `code_title_id` and `status` filters. Submissions are read individually, exposing the conflict partner and the resolution basis, or listed with optional `cycle_id`, `instrument_id`, `conflict_with_submission_id` and `status` filters. Titles are read individually, exposing `section_refs` and `current_supplement_number`, or listed with an optional `status` filter.

### 3.8. Public Records Requests: Two Independent Axes

A public records request is the one resource in this service that a member of the public creates, and it is tracked along **two axes that never move each other**. `fulfillment_status` is the disclosure axis and answers what the office has released; `fee_status` is the money axis and answers what the requester owes. Every operation on the disclosure axis leaves `fee_status` untouched, and every operation on the money axis leaves `fulfillment_status` untouched. Only the withdrawal, which abandons the request entirely, moves both at once.

Intake is open to the public: an `Anonymous` caller, a `CityClerk` or a `DeputyClerk` files the request with the `requester_name` as filed, a `requester_email` for the response, and a `subject_description` naming the records sought. Two optional inputs shape what follows. `target_series_id` names the retention series the request reaches into, and is null when the request names no series — a request that names one can later block the destruction of that series. `commercial_purpose` is a declaration, false by default, that the records are sought for commercial gain; it costs the requester a surcharge at assessment time. The request enters with `fulfillment_status` `RECEIVED`, `fee_status` `NOT_ASSESSED`, `exemption_count` 0, every money counter at 0, and `intake_on` set to the logical clock date. **The `id` of the created request is the credential the requester uses thereafter**: it is the value that must be presented as `X-User-ID` under the `Requester` role.

The statutory response deadline is computed at intake and stored as `due_on`. It is five **business days** after intake, counted by walking the calendar forward one day at a time from `intake_on` and decrementing the count only on days that are Monday through Friday; Saturdays and Sundays are skipped and never consume a count. The day of intake itself is never counted, and because the walk only ever stops on a weekday, `due_on` always lands on a weekday.

On the disclosure axis, a `CityClerk` or `DeputyClerk` opens the file, moving `RECEIVED → UNDER_REVIEW`. A `RecordsOfficer` then conducts the exemption review, supplying `exemption_claims` — the statutory exemptions asserted over the responsive records — which moves the request `UNDER_REVIEW → EXEMPTION_REVIEW` and sets `exemption_count` to the number of claims supplied. The disposition is recorded by a `CityClerk` or a `RecordsOfficer` and takes one of three values in `disposition`. A `FULL_RELEASE` may be recorded from either `UNDER_REVIEW` or `EXEMPTION_REVIEW` and moves the request to `RELEASED`. A `PARTIAL_RELEASE` may likewise be recorded from either state but requires that `exemption_count` be at least 1 — something must have been withheld for the release to be partial — and moves the request to `PARTIALLY_RELEASED`. A `DENIAL` may be recorded only from `EXEMPTION_REVIEW`, requires `exemption_count` to be at least 1, and requires `denial_basis`, the statutory exemption cited; it moves the request to `DENIED` and records the basis, which is null on any request that was not denied. A partial release or a denial attempted while `exemption_count` is 0 is refused with `ERR_DENIAL_WITHOUT_EXEMPTION` (HTTP 422).

Closing is a `CityClerk` act and has two preconditions in a fixed order. The request must first be in `RELEASED`, `PARTIALLY_RELEASED` or `DENIED`; anything else is `ERR_REQUEST_NOT_CLOSABLE` (HTTP 409). Only then is the money examined: `fee_balance_cents` must be exactly 0, or the close is refused with `ERR_FEE_BALANCE_OUTSTANDING` (HTTP 409). A request that is neither disposed of nor paid up therefore reports the closability failure, not the balance failure. On success `fulfillment_status` becomes `CLOSED` and `closed_on` records the logical clock date — and if the request names a `target_series_id` whose series runs its retention from request closure, that closure has just supplied the series' retention anchor, so the series' eligibility date is recomputed on the spot.

Withdrawal is available to the `Requester` on its own request and to a `CityClerk`, from any state that is not already `CLOSED` or `WITHDRAWN`, and it is the one operation that moves both axes. `fulfillment_status` becomes `WITHDRAWN`, and the fee ledger is unwound by compensation rather than by deletion: `total_waived_cents` is set equal to `total_assessed_cents` and `refunded_cents` is set equal to `total_collected_cents`, which drives both derived money fields to exactly 0. `fee_status` then becomes `REFUNDED` if any money had actually been collected, or `WAIVED` if a fee had been assessed but never paid, or is left at `NOT_ASSESSED` if no fee had ever been assessed. `CLOSED` and `WITHDRAWN` are the two terminal states of the disclosure axis.

On the money axis, a fee is assessed exactly once, by a `CityClerk` or `DeputyClerk`, and only while the request is neither `CLOSED` nor `WITHDRAWN`. A second attempt against a request whose `fee_status` has already left `NOT_ASSESSED` is refused with `ERR_FEE_ALREADY_ASSESSED` (HTTP 422). The caller chooses a `fee_schedule_variant` — either `ACTUAL_COST` or `FLAT_SCHEDULE` — and supplies `fee_lines`, a list in which each line carries a `page_count`, a number of `staff_minutes`, and a `delivery_medium` of either `PAPER` or `ELECTRONIC`. The chosen variant is recorded on the request, because the two schedules produce **different totals from identical lines**: they differ not in their rates alone but in *where* the free allowances and the rounding land.

Under `ACTUAL_COST` each line is priced on its own quantities. A free allowance of 20 pages is carried into the first line and consumed line by line in the order the lines were supplied: a line's billable pages are its `page_count` less whatever allowance remains, floored at zero, and the remaining allowance is then reduced by that line's full `page_count`, floored at zero. Each line's billable pages are charged at 15 cents per page, and if that line's `delivery_medium` is `ELECTRONIC` its own charge is then halved and rounded half up to a whole cent. The copy charges of all lines are summed. Staff time under this variant is converted **per line**: each line's `staff_minutes` is divided by 15 and rounded up to a whole quarter-hour, and those per-line quarter-hours are then added together. The first 2 quarter-hours — the first half hour of staff time — are free, so the billable quarter-hours are the total less two, floored at zero, and each billable quarter-hour costs 875 cents.

Under `FLAT_SCHEDULE` the quantities are pooled before anything is priced. The `page_count` of every line is summed first, the 20-page allowance is deducted once from that total with the result floored at zero, and the remaining pages are charged at the flat rate of 25 cents per page — with **no electronic discount at all**, whatever any line's `delivery_medium` says. The `staff_minutes` of every line are likewise summed first, and the pooled minutes are divided by 15 and rounded up to a whole quarter-hour **once**, rather than per line; the same 2 free quarter-hours are then deducted, floored at zero, and the remainder charged at 875 cents each.

Both variants finish the same way. The copy charge and the staff charge are added into a subtotal, and if the request declared a `commercial_purpose`, that subtotal is increased by one fifth — multiplied by 1.20 — and rounded half up to a whole cent; without a commercial declaration the subtotal stands as it is. The result is `total_assessed_cents`, `fee_schedule_variant` is stored, `fee_status` moves `NOT_ASSESSED → ASSESSED`, and the ledger is recomputed.

The ledger itself is four stored counters and two derived readings, and the derived readings are recomputed from the counters on **every** money-axis write rather than being patched incrementally. `net_cash_cents` is `total_collected_cents` less `refunded_cents` — the conserved cash position of the request. `fee_balance_cents` is `total_assessed_cents`, less `total_waived_cents`, less that net cash position. Neither reading may ever go negative, which is what constrains the two ways money moves.

A payment is recorded by the `Requester` on its own request or by a `CityClerk`, supplying `amount_cents`. A fee must already have been assessed, or the payment is `ERR_FEE_NOT_ASSESSED` (HTTP 422), and the amount may not exceed the current `fee_balance_cents`, or it is `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422). The amount is added to `total_collected_cents` and the ledger is recomputed. A payment that leaves a balance behind moves `fee_status` to `DEPOSIT_HELD`; a payment that settles the balance exactly moves it to `PAID`.

A waiver is a `RecordsOfficer` act, supplying `waived_cents` and a `waiver_reason` for the file. The waived amount may not exceed the current `fee_balance_cents`, or the waiver is `ERR_WAIVER_EXCEEDS_BALANCE` (HTTP 422). The amount is added to `total_waived_cents` and the ledger is recomputed. What the waiver does to `fee_status` depends on whether cash was ever taken: if the balance now reads 0 and `net_cash_cents` is also 0, the request is `WAIVED`; if the balance now reads 0 but cash has been collected and not refunded, the request is `PAID`; and if the balance is still above 0, `fee_status` is left exactly as it was. The money axis therefore runs `NOT_ASSESSED` → `ASSESSED` → `DEPOSIT_HELD` → `PAID`, with `WAIVED` reachable from an assessed or deposit-held request and `REFUNDED` reachable from a paid request that is later withdrawn.

A request is read individually — exposing both axes and the whole ledger — by a `Requester` on its own request, or by a `CityClerk`, `DeputyClerk` or `RecordsOfficer`. Staff may also list requests with optional `target_series_id`, `fulfillment_status` and `fee_status` filters; that listing is not available to a `Requester`.

### 3.9. The Retention Schedule, Custody and Certified Destruction

The retention schedule is a list of record series, each describing a class of records and how long the city must keep it. A `RecordsOfficer` adds one with its `series_code`, the schedule item code, which must be unique across the schedule — a duplicate is `ERR_DUPLICATE_SERIES_CODE` (HTTP 422) — its `name` as the caption on the schedule, its `retention_years`, a whole number of years from 0 up to and including 100 that the series must be kept past its anchor, and its `retention_trigger`, naming which anchor date the retention period runs from. Two optional flags complete it: `permanent`, false by default, marking a series that may **never** be destroyed, and `legal_hold_status`, which is `NONE` by default and may be `LITIGATION_HOLD` or `AUDIT_HOLD`. The officer may later place or lift a hold, or flag the series permanent; each such change advances the series' `version` and recomputes its eligibility date. A new series starts with `total_accessioned_count`, `active_item_count` and `destroyed_item_count` all at 0, `last_accessioned_on` null, and `eligible_through_on` null, because no anchor exists yet.

Items enter custody by accession, performed by a `RecordsOfficer` or a `DeputyClerk`, who supplies the `item_count` accessioned and the `accessioned_on` date they bear. The accession advances `total_accessioned_count` by that count and `active_item_count` by the same count, and sets `last_accessioned_on` to the later of its existing value and the supplied date, so the anchor only ever moves forward. The eligibility date is then recomputed.

`eligible_through_on` is the last date through which the series must be kept, and it is derived from the anchor the trigger names. Under `CREATION` the anchor is the series' `last_accessioned_on`. Under `FISCAL_YEAR_END` the anchor is the first 30 June falling on or after `last_accessioned_on` — the city's fiscal year ends on 30 June, so records accessioned in early June anchor to that same June while records accessioned in July anchor to the following one. Under `REQUEST_CLOSURE` the anchor is the latest `closed_on` among the closed public records requests whose `target_series_id` is this series, and where no such request exists the anchor is simply **unresolved**. Given an anchor, `eligible_through_on` is that anchor plus `retention_years` whole years. Where the series is flagged `permanent`, or where the anchor is unresolved, `eligible_through_on` is null.

Proposing a destruction batch is available to a `RecordsOfficer` or a `DeputyClerk`, who names the `series_id`, the `item_count` proposed for destruction — at least 1 — and a `cutoff_on` date meaning that records dated on or before it are in the batch. Four gates apply, in this order. The series must not be under a hold, or the proposal is `ERR_SERIES_UNDER_LEGAL_HOLD` (HTTP 409), and it must not be flagged permanent, or the proposal is `ERR_SERIES_PERMANENT_RETENTION` (HTTP 409). Then the retention clock: `eligible_through_on` must be resolvable at all, or the proposal is `ERR_RETENTION_ANCHOR_UNRESOLVED` (HTTP 409), and it must have elapsed — it must fall at or before the logical clock date, and `cutoff_on` must fall at or before it — or the proposal is `ERR_RETENTION_PERIOD_NOT_ELAPSED` (HTTP 409). Finally the batch may not propose more items than the series actually holds: an `item_count` above the series' `active_item_count` is `ERR_DESTRUCTION_COUNT_EXCEEDS_ACTIVE` (HTTP 422). The hold and permanence checks are evaluated **before** the item-count check, so a batch that is both held and oversized reports the hold.

A proposed batch records who proposed it in `proposed_by_officer_id`, taken from the acting `X-User-ID`, and snapshots the series' `eligible_through_on` into its own `eligible_through_on` field, freezing what the schedule said at proposal time even as the series' own date continues to move. It also records `blocking_request_id`: the earliest-created public records request whose `target_series_id` is this series and whose `fulfillment_status` is neither `CLOSED` nor `WITHDRAWN`, or null when there is none. The batch enters at `status` `PROPOSED` with `certifying_officer_id`, `certified_on` and `rescind_reason` all null.

Signing the certificate of destruction is available to a `CityClerk` or a `RecordsOfficer` and requires a second pair of hands: the acting `X-User-ID` must differ from the batch's `proposed_by_officer_id`, or the signature is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The series must still be free of any hold. `blocking_request_id` is **recomputed at this moment** rather than trusted from proposal time, and if it now resolves to a request, the certification is refused with `ERR_SERIES_HAS_OPEN_REQUEST` (HTTP 409) — a records request filed after the batch was proposed still stops the shredder. The batch's `item_count` is re-checked against the series' current `active_item_count` and an excess is again `ERR_DESTRUCTION_COUNT_EXCEEDS_ACTIVE`. On success the batch moves `PROPOSED → CERTIFIED`, `certifying_officer_id` records the signer's `X-User-ID`, `certified_on` records the supplied date, and the custody counters move: `active_item_count` falls by the batch's `item_count` and `destroyed_item_count` rises by the same amount.

Custody is conserved at every observable moment: `total_accessioned_count` always equals `active_item_count` plus `destroyed_item_count`. Destruction moves items between the two sub-counters and **never** changes the custody total, which is why an oversized batch is refused outright rather than driving `active_item_count` below zero.

A certificate can be rescinded, by a `RecordsOfficer` only, from `CERTIFIED`. The officer supplies a `rescind_reason`, the batch moves `CERTIFIED → RESCINDED`, and the counter movement is undone exactly: `active_item_count` rises by the batch's `item_count` and `destroyed_item_count` falls by the same amount, returning the series to precisely the three counter values it held before the certification, with no drift in either direction and again no change to `total_accessioned_count`. `certifying_officer_id` and `certified_on` are deliberately **retained** on the rescinded batch for audit, alongside the reason. `RESCINDED` is terminal.

Series are read individually, exposing the custody counters and `eligible_through_on`. Batches are read individually, exposing the blocking request and both signatures, or listed with optional `series_id`, `blocking_request_id` and `status` filters.

## 4. Endpoint Definitions

Creation endpoints answer HTTP 201 with the newly created resource in `data`; every other successful operation, including all state transitions and all reads, answers HTTP 200. Endpoints that transition or mutate a resource return that resource's current representation, except where section 3 states otherwise — an accession, for instance, returns the affected `RecordSeries` rather than a separate accession record, and a conflict resolution returns the submission named in the path whichever side of the conflict it landed on. This table is deliberately minimal: request bodies, response payloads and side effects are specified in the narrative of sections 2 and 3, not here.

In the Authorized Role(s) column, **All staff roles** means the five internal roles `CityClerk`, `DeputyClerk`, `PresidingOfficer`, `RecordsOfficer` and `CodificationEditor`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clerk/_clock/set_current_utc` | Sets the server's logical clock to an arbitrary instant. | All staff roles |
| POST | `/clerk/venues` | Registers a meeting venue and its teardown buffer. | `CityClerk` |
| GET | `/clerk/venues/{venue_id}` | Reads one venue. | All staff roles |
| PUT | `/clerk/venues/{venue_id}` | Updates the venue's capacity, teardown buffer or availability. | `CityClerk` |
| POST | `/clerk/number-series` | Opens an ordinance or resolution numbering series for one series year. | `CityClerk` |
| GET | `/clerk/number-series/{series_id}` | Reads one numbering series, including its next sequence and minted count. | All staff roles |
| POST | `/clerk/number-series/{series_id}/close` | Closes a numbering series so no further numbers may be minted from it. | `CityClerk` |
| POST | `/clerk/meetings` | Schedules a meeting, reserving the venue window plus the venue teardown buffer. | `CityClerk` |
| GET | `/clerk/meetings/{meeting_id}` | Reads one meeting, including its mirrored notice fields. | All staff roles |
| GET | `/clerk/meetings` | Lists meetings, optionally filtered by venue or status. | All staff roles |
| POST | `/clerk/meetings/{meeting_id}/reschedule` | Moves a scheduled or noticed meeting to a new window, re-running the notice and venue checks. | `CityClerk` |
| POST | `/clerk/meetings/{meeting_id}/convene` | Calls the meeting to order; requires a compliant notice and a quorum. | `PresidingOfficer` |
| POST | `/clerk/meetings/{meeting_id}/adjourn` | Adjourns the meeting, opens its draft minutes and withdraws every un-tallied motion. | `PresidingOfficer` |
| POST | `/clerk/meetings/{meeting_id}/cancel` | Cancels a scheduled or noticed meeting, withdrawing its packets and voiding its agenda notice. | `CityClerk` |
| POST | `/clerk/meetings/{meeting_id}/agenda-packets` | Creates the next agenda packet revision for a meeting, superseding the prior revision. | `CityClerk` |
| GET | `/clerk/meetings/{meeting_id}/agenda-packets` | Lists every agenda packet revision of one meeting. | All staff roles |
| GET | `/clerk/agenda-packets/{packet_id}` | Reads one agenda packet, including its notice arithmetic. | All staff roles |
| GET | `/clerk/agenda-packets` | Lists agenda packets across meetings, filterable by meeting and revision status. | All staff roles |
| POST | `/clerk/agenda-packets/{packet_id}/agenda-items` | Adds an immutable item to a draft packet. | `CityClerk`, `DeputyClerk` |
| GET | `/clerk/agenda-packets/{packet_id}/agenda-items` | Lists the items of one packet in printed sequence order. | All staff roles |
| GET | `/clerk/agenda-items/{item_id}` | Reads one agenda item. | All staff roles |
| GET | `/clerk/agenda-items` | Lists agenda items across packets, filterable by packet and item type. | All staff roles |
| POST | `/clerk/agenda-packets/{packet_id}/post` | Posts the packet, notices the meeting and records whether the statutory notice deadline was met. | `CityClerk` |
| POST | `/clerk/agenda-packets/{packet_id}/withdraw` | Withdraws a draft or posted packet, un-noticing the meeting when the packet was the posted one. | `CityClerk` |
| GET | `/clerk/meetings/{meeting_id}/minutes` | Lists the minutes records of one meeting. | All staff roles |
| GET | `/clerk/minutes/{minutes_id}` | Reads one minutes record, including any pending correction text. | All staff roles |
| GET | `/clerk/minutes` | Lists minutes records across meetings, filterable by meeting and approval status. | All staff roles |
| PUT | `/clerk/minutes/{minutes_id}` | Writes the narrative of a draft minutes record. | `CityClerk`, `DeputyClerk` |
| POST | `/clerk/minutes/{minutes_id}/submit` | Submits draft minutes for approval at a later meeting. | `CityClerk` |
| POST | `/clerk/minutes/{minutes_id}/corrections` | Opens a correction against approved minutes. | `CityClerk`, `DeputyClerk` |
| POST | `/clerk/instruments` | Introduces an ordinance or resolution against an open numbering series. | `CityClerk` |
| GET | `/clerk/instruments/{instrument_id}` | Reads one instrument, including its assigned number, effective-date basis and effective date. | All staff roles |
| GET | `/clerk/instruments` | Lists instruments, optionally filtered by numbering series, code title or status. | All staff roles |
| POST | `/clerk/instruments/{instrument_id}/advance-reading` | Records a first reading of an ordinance at a meeting in session. | `CityClerk` |
| POST | `/clerk/instruments/{instrument_id}/veto` | Vetoes an adopted ordinance, voiding its pending publication notice. | `PresidingOfficer` |
| POST | `/clerk/motions` | Records a moved-and-seconded motion at a meeting in session. | `CityClerk`, `DeputyClerk` |
| GET | `/clerk/motions/{motion_id}` | Reads one motion, including the vote arithmetic and whether its result is official. | All staff roles |
| GET | `/clerk/motions` | Lists motions, optionally filtered by meeting, agenda item, instrument, target minutes or status. | All staff roles |
| POST | `/clerk/motions/{motion_id}/tally` | Records the vote and resolves the motion, driving every downstream cascade. | `CityClerk` |
| GET | `/clerk/publication-notices/{notice_id}` | Reads one publication notice, including its invoice arithmetic. | All staff roles |
| GET | `/clerk/publication-notices` | Lists publication notices, optionally filtered by instrument, meeting or status. | All staff roles |
| POST | `/clerk/publication-notices/{notice_id}/order` | Places the insertion order with the newspaper of record and prices the invoice. | `CityClerk`, `DeputyClerk` |
| POST | `/clerk/publication-notices/{notice_id}/certify-publication` | Certifies that the ordered insertions ran, driving the publication-to-codification cascade. | `CityClerk` |
| POST | `/clerk/code-titles` | Creates a municipal code title. | `CodificationEditor` |
| GET | `/clerk/code-titles/{title_id}` | Reads one code title, including its section references and current supplement number. | All staff roles |
| GET | `/clerk/code-titles` | Lists code titles. | All staff roles |
| POST | `/clerk/code-titles/{title_id}/supplement-cycles` | Opens a supplement cycle over an inclusive submission window on one code title. | `CodificationEditor` |
| GET | `/clerk/code-titles/{title_id}/supplement-cycles` | Lists the supplement cycles of one code title. | All staff roles |
| GET | `/clerk/supplement-cycles/{cycle_id}` | Reads one supplement cycle, including its submission and conflict counters. | All staff roles |
| GET | `/clerk/supplement-cycles` | Lists supplement cycles across code titles, filterable by code title and cycle status. | All staff roles |
| POST | `/clerk/supplement-cycles/{cycle_id}/lock` | Closes the cycle to new filings and moves its pending submissions into review. | `CodificationEditor` |
| POST | `/clerk/supplement-cycles/{cycle_id}/certify` | Certifies the supplement into the code, rewriting the title's section list. | `CodificationEditor` |
| POST | `/clerk/codification-submissions` | Files a client-origin codification submission into an open cycle. | `CodificationEditor` |
| GET | `/clerk/codification-submissions/{submission_id}` | Reads one submission, including its conflict partner and resolution basis. | All staff roles |
| GET | `/clerk/codification-submissions` | Lists submissions, optionally filtered by cycle, instrument, conflict partner or status. | All staff roles |
| POST | `/clerk/codification-submissions/{submission_id}/decide` | Accepts or rejects a submission that is in review inside a locked cycle. | `CodificationEditor` |
| POST | `/clerk/codification-submissions/{submission_id}/resolve-conflict` | Resolves an old-versus-new provision conflict under the requested precedence basis. | `CodificationEditor` |
| POST | `/clerk/records-requests` | Intakes a public records request and computes its statutory response deadline. | `Anonymous`, `CityClerk`, `DeputyClerk` |
| GET | `/clerk/records-requests/{request_id}` | Reads one request, including both status axes and the fee ledger. | `Requester`, `CityClerk`, `DeputyClerk`, `RecordsOfficer` |
| GET | `/clerk/records-requests` | Lists requests, optionally filtered by target series or either status axis. | `CityClerk`, `DeputyClerk`, `RecordsOfficer` |
| POST | `/clerk/records-requests/{request_id}/begin-review` | Opens the file, moving the disclosure axis into review. | `CityClerk`, `DeputyClerk` |
| POST | `/clerk/records-requests/{request_id}/exemption-review` | Records the statutory exemptions asserted over the responsive records. | `RecordsOfficer` |
| POST | `/clerk/records-requests/{request_id}/assess-fee` | Assesses the copy and staff-time fee under the requested fee schedule. | `CityClerk`, `DeputyClerk` |
| POST | `/clerk/records-requests/{request_id}/waive-fee` | Waives part or all of the outstanding balance. | `RecordsOfficer` |
| POST | `/clerk/records-requests/{request_id}/payments` | Records a payment against the assessed fee. | `Requester`, `CityClerk` |
| POST | `/clerk/records-requests/{request_id}/disposition` | Releases, partially releases or denies the records. | `CityClerk`, `RecordsOfficer` |
| POST | `/clerk/records-requests/{request_id}/withdraw` | Withdraws the request and unwinds the entire fee ledger to zero. | `Requester`, `CityClerk` |
| POST | `/clerk/records-requests/{request_id}/close` | Closes a disposed request; may release a retention anchor. | `CityClerk` |
| POST | `/clerk/record-series` | Adds an item to the retention schedule. | `RecordsOfficer` |
| GET | `/clerk/record-series/{series_id}` | Reads one retention series, including the custody counters and eligibility date. | All staff roles |
| PUT | `/clerk/record-series/{series_id}` | Places or lifts a legal hold, or flags the series permanent. | `RecordsOfficer` |
| POST | `/clerk/record-series/{series_id}/accessions` | Accessions items into custody, moving the retention anchor forward. | `RecordsOfficer`, `DeputyClerk` |
| POST | `/clerk/destruction-batches` | Proposes a batch for destruction under the retention schedule. | `RecordsOfficer`, `DeputyClerk` |
| GET | `/clerk/destruction-batches/{batch_id}` | Reads one destruction batch, including its blocking request and certification signatures. | All staff roles |
| GET | `/clerk/destruction-batches` | Lists destruction batches, optionally filtered by series, blocking request or status. | All staff roles |
| POST | `/clerk/destruction-batches/{batch_id}/certify` | Signs the certificate of destruction. | `CityClerk`, `RecordsOfficer` |
| POST | `/clerk/destruction-batches/{batch_id}/rescind` | Rescinds a certificate of destruction, restoring the custody counters exactly. | `RecordsOfficer` |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in `data.error_id`, with the HTTP status shown. Trigger conditions are not repeated here; each is stated in the section 2 or section 3 narrative that governs the rule it enforces.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_MEETING_NOT_FOUND` | 404 |
| `ERR_PACKET_NOT_FOUND` | 404 |
| `ERR_AGENDA_ITEM_NOT_FOUND` | 404 |
| `ERR_MOTION_NOT_FOUND` | 404 |
| `ERR_MINUTES_NOT_FOUND` | 404 |
| `ERR_NUMBER_SERIES_NOT_FOUND` | 404 |
| `ERR_INSTRUMENT_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_CODE_TITLE_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_REQUEST_NOT_FOUND` | 404 |
| `ERR_SERIES_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_STALE_MEETING_VERSION` | 412 |
| `ERR_STALE_CODE_TITLE_VERSION` | 412 |
| `ERR_STALE_MINUTES_VERSION` | 412 |
| `ERR_INVALID_MEETING_STATE` | 409 |
| `ERR_INVALID_PACKET_STATE` | 409 |
| `ERR_INVALID_MOTION_STATE` | 409 |
| `ERR_INVALID_MINUTES_STATE` | 409 |
| `ERR_INVALID_INSTRUMENT_STATE` | 409 |
| `ERR_INVALID_NOTICE_STATE` | 409 |
| `ERR_INVALID_SUBMISSION_STATE` | 409 |
| `ERR_INVALID_BATCH_STATE` | 409 |
| `ERR_INVALID_REQUEST_STATE` | 409 |
| `ERR_MEETING_NOT_IN_SESSION` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_CYCLE_NOT_LOCKED` | 409 |
| `ERR_NUMBER_SERIES_CLOSED` | 409 |
| `ERR_CYCLE_HAS_OPEN_SUBMISSIONS` | 409 |
| `ERR_UNRESOLVED_CONFLICTS` | 409 |
| `ERR_REQUEST_NOT_CLOSABLE` | 409 |
| `ERR_NOTICE_DEADLINE_MISSED` | 409 |
| `ERR_QUORUM_NOT_MET` | 409 |
| `ERR_VOTE_TALLY_MISMATCH` | 422 |
| `ERR_NO_VOTING_MEMBERS` | 422 |
| `ERR_SERIES_UNDER_LEGAL_HOLD` | 409 |
| `ERR_SERIES_PERMANENT_RETENTION` | 409 |
| `ERR_SERIES_HAS_OPEN_REQUEST` | 409 |
| `ERR_CYCLE_SUBMISSION_CAPACITY` | 422 |
| `ERR_PACKET_REVISION_LIMIT` | 422 |
| `ERR_NUMBER_SERIES_EXHAUSTED` | 422 |
| `ERR_DUPLICATE_NUMBER_SERIES` | 422 |
| `ERR_DUPLICATE_SUPPLEMENT_NUMBER` | 422 |
| `ERR_DUPLICATE_SEQUENCE_NUMBER` | 422 |
| `ERR_DUPLICATE_SERIES_CODE` | 422 |
| `ERR_DUPLICATE_CODE_TITLE` | 422 |
| `ERR_DESTRUCTION_COUNT_EXCEEDS_ACTIVE` | 422 |
| `ERR_VENUE_WINDOW_CONFLICT` | 409 |
| `ERR_VENUE_CLOSED` | 409 |
| `ERR_SUPPLEMENT_WINDOW_CONFLICT` | 409 |
| `ERR_PUBLICATION_COUNT_MISMATCH` | 409 |
| `ERR_PUBLICATION_DEADLINE_MISSED` | 409 |
| `ERR_PUBLICATION_INTERVAL_TOO_SHORT` | 409 |
| `ERR_OUTSIDE_SUBMISSION_WINDOW` | 409 |
| `ERR_RETENTION_ANCHOR_UNRESOLVED` | 409 |
| `ERR_RETENTION_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_FEE_BALANCE_OUTSTANDING` | 409 |
| `ERR_FEE_NOT_ASSESSED` | 422 |
| `ERR_FEE_ALREADY_ASSESSED` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_WAIVER_EXCEEDS_BALANCE` | 422 |
| `ERR_CODE_SECTION_UNKNOWN` | 422 |
| `ERR_SERIES_CLASS_MISMATCH` | 422 |
| `ERR_MOTION_TARGET_INVALID` | 422 |
| `ERR_EMPTY_AGENDA_PACKET` | 422 |
| `ERR_DENIAL_WITHOUT_EXEMPTION` | 422 |
| `ERR_NO_OPEN_SUPPLEMENT_CYCLE` | 409 |
