# Public Meeting & Open Records Portal API — Product Requirements Document

## 1. Introduction

Local governing bodies operate under two overlapping bodies of law: open-meetings statutes that dictate how and when the public must be told a meeting will occur, and open-records (FOIA / state public-records) statutes that dictate how requests for government documents are intaked, priced, fulfilled, and appealed. This API unifies both mandates behind a single portal. On the meetings side it governs the full arc of a public meeting: scheduling a room and a presiding chair, posting statutory notice, convening with a quorum, running an agenda of items and motions, taking public comment through a speaker queue, recording a roll-call vote, and publishing minutes. On the records side it governs the intake of a records request, the review and redaction of responsive documents, the assessment of copying and labor fees, the fulfillment or denial of the request, and the independent appeal of that determination.

The system is deliberately strict about compliance and segregation of duties. Notice must lead a meeting by a statutory number of hours that depends on the meeting type; a meeting cannot convene without quorum; an appeals officer may never rule on an appeal of a determination they themselves issued; and a document may not be destroyed until its retention schedule has elapsed. Because determinations price a snapshot of a moving document set, the records workflow is guarded by optimistic concurrency control. The remainder of this document specifies the entities, their state machines, the calculations that price fees and tally votes, and the validation ordering that resolves competing failures.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request (other than the explicitly public operations noted below) must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes six roles, spelled exactly: `Clerk`, `BodyMember`, `RecordsOfficer`, `AppealsOfficer`, `Requester`, and `Anonymous`. A request that omits or supplies an invalid header pair on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not permitted for the target operation is rejected with `ERR_UNAUTHORIZED`.

Two roles are **entity-backed**, meaning their `X-User-ID` is the identifier of a persisted record and is used for ownership checks. When `X-User-Role` is `Requester`, `X-User-ID` is the `id` of the acting `Requester`; ownership checks on any resource that references a `Requester` compare that resource's `requester_id` to `X-User-ID`. When `X-User-Role` is `BodyMember`, `X-User-ID` is the `id` of the acting `BodyMember`; presiding-officer checks compare the parent meeting's `presiding_member_id` to `X-User-ID`, and vote/motion authorship compares member identifiers to it as well.

The remaining roles are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity's `id`. When `X-User-Role` is `RecordsOfficer`, the server records the acting id as `determined_by_user_id` on the request the officer determines, but never compares it to any entity `id`; it is later read back only to enforce segregation of duties. When `X-User-Role` is `AppealsOfficer`, the server records the acting id as `decided_by_user_id` on the appeal under review and compares it, for segregation-of-duties purposes only, against the request's `determined_by_user_id`. When `X-User-Role` is `Clerk`, the id is an opaque audit identifier the server may log but never compares to an entity `id`. `Anonymous` denotes an unauthenticated caller; it carries no meaningful identity and is accepted only where an endpoint explicitly lists it — self-registration as a requester and the public reads of meetings, agenda items, motions, and speaker slips.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a list endpoint states otherwise, results are ordered by `created_at` in ascending order (the speaker-slip list is ordered by queue position, which is itself derived from `created_at` ascending). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Several list endpoints additionally accept a `status` filter, and the records-request list additionally accepts `requester_id` and `body_id` filters.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Because all entities in this system are mutable audit subjects, each also carries an `updated_at` timestamp (ISO 8601 UTC) and an integer `version`. The `version` begins at 1 on creation and increases by exactly 1 on every mutation of the resource; `updated_at` is refreshed to the logical-clock instant of each mutation. When a computed field changes as a side effect of an operation (for example a fee balance or a vote tally), that too is a mutation that refreshes `updated_at` and increments `version`.

### 2.5. Nested Resource Retrieval and Path Validation

Many resources are addressed through nested paths that name more than one identifier — a document under a request, or an appeal under a request. For any such path the server validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A document transition addressed under a request first confirms the request exists, then the document. This left-to-right rule holds for creation, transition, and read operations alike.

### 2.6. The Logical Clock and Temporal Governance

All time-sensitive rules are evaluated against a server **logical clock** rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time before it is set. A clock-setting capability, reserved to the `Clerk` role, advances the logical clock to a supplied `to_iso8601` instant. The logical clock is the reference for four gates: notice lead time when convening, the response deadline stamped on a records request, the appeal-filing window, and the elapsed-retention check before a document may be destroyed. Logical-clock instants are also what the server stamps into system timestamps such as `notice_posted_at`, `submitted_at`, `filed_at`, `called_at`, `determined_at`, `minutes_approved_at`, and the moment of each disposition.

### 2.7. Cascading State Propagation and Hierarchical Consistency

Operations frequently mutate more than the resource named in the request. When a meeting is cancelled, when an agenda item closes or is cancelled, when a request is withdrawn, and when an appeal is remanded or overturned, the server automatically transitions dependent child resources and reconciles derived fields without a separate client request against each child. Every child the server touches during such a cascade is itself a mutation that refreshes the child's `updated_at` and increments its `version`. The precise cascade sets are specified inline in §3 where each triggering transition is described; the governing principle here is that these secondary effects are mandatory and atomic with the primary transition, not optional cleanup.

### 2.8. Optimistic Concurrency Control on Determinations

Issuing a determination against a records request is guarded by optimistic concurrency control, because a determination prices a snapshot of the request's responsive-document set and that set changes over time. Attaching a responsive document to a request increments the request's `version`; so does any other mutation of the request. A determination request must therefore carry `expected_records_request_version` as a required field holding the `version` the officer last observed. If that value does not equal the request's current `version`, the determination is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the officer from pricing a document set that has been altered since they read it. No other endpoint takes a version field; only the determination is version-checked.

### 2.9. Fees, the Money Ledger, and Precision

Fees are always held as integer cents; no fractional cent ever appears. Copy fees are computed as exact integer cents. Labor fees and the assessed fee are computed with the **round-half-up** convention at the single rounding point specified in §3. Each records request maintains a small money ledger across four fields: the computed `assessed_fee_cents`, the `amount_waived_cents` applied as a public-interest waiver at determination, the cumulative `amount_paid_cents` received, and the derived `fee_balance_cents`. The balance is always the assessed fee minus the waiver minus the cumulative payments. For any determined request the conservation identity holds at all times: the assessed fee equals the sum of the waiver, the cumulative payments, and the outstanding balance. Payments and waivers move money between these accounts but never change their sum.

### 2.10. Validation Ordering

When more than one rule could reject a request, the server evaluates them in a fixed priority order and returns the first failure. The order is: (1) authentication of the header pair, failing with `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint, failing with `ERR_UNAUTHORIZED`; (3) resource ownership for entity-backed requesters, failing with `ERR_NOT_RESOURCE_OWNER`; (4) presiding-officer gating for body-member actions, failing with `ERR_NOT_PRESIDING_OFFICER`; (5) segregation of duties on appeal review, failing with `ERR_SEGREGATION_OF_DUTIES`; (6) existence of all path-referenced resources, validated left-to-right, failing with `ERR_NOT_FOUND`; (7) request-body well-formedness — required fields present, enums valid, numeric ranges honored, `scheduled_end` strictly after `scheduled_start`, mover distinct from seconder, waiver not exceeding the assessed fee — failing with `ERR_VALIDATION` (or the specific `ERR_MOVER_SECONDER_SAME` / `ERR_WAIVER_EXCEEDS_FEE`); (8) optimistic-concurrency match of `expected_records_request_version`, failing with `ERR_STALE_VERSION`; (9) legality of the requested state transition from the current state and any cross-dimension or cross-entity state guard, failing with `ERR_INVALID_STATE` or its specific variants; (10) temporal compliance gates for notice, appeal window, and retention; (11) resource-conflict and quorum constraints for venue, presiding overlap, quorum count, and comment cap; and (12) the fiscal gate that bars closing a granted request while money is owed. This ordering means, for instance, that an unauthorized caller is rejected before existence is checked, and that a stale-version determination is rejected before its target-state legality is considered.

## 3. Business Logic & Workflows

### 3.1. Establishing a Governing Body

A `Clerk` bootstraps the system by creating a **public body** — a governing body such as a city council. Creation supplies the body's `name`, its `jurisdiction_state` (the two-letter US state code whose open-meetings and open-records law governs it), a `seat_count` of at least 1 giving the total authorized voting seats, and a `quorum_size` giving the minimum members that must be present to convene. The quorum size must be at least 1 and no greater than the seat count.

Into a body the clerk adds **members** and **venues**. A member is created with a `full_name` and a `seat_number` between 1 and the body's seat count inclusive; the server records the owning body on the member's `body_id` and sets the member's `status` to `ACTIVE` by default, where the lifecycle values are `ACTIVE`, `RECUSED`, and `VACANT`. The member list may be filtered by `status`. A venue is created with a `name` and an optional `capacity` that defaults to 50 when omitted; its `body_id` is likewise stamped by the server. Members and venues both belong to exactly one body and are reached by listing under that body.

### 3.2. Scheduling a Meeting and Detecting Conflicts

A `Clerk` schedules a **meeting** under a public body by supplying the `venue_id` of a room and the `presiding_member_id` of the chair (both of which must belong to that same body), a `title`, a `meeting_type` of `REGULAR`, `SPECIAL`, or `EMERGENCY`, and a `scheduled_start` and `scheduled_end` in ISO 8601 UTC where the end is strictly after the start. A newly scheduled meeting takes `SCHEDULED` on its lifecycle dimension (`status`) and `NONE` on its minutes dimension (`minutes_status`).

Before the meeting is accepted, two distinct interval conflicts are checked against the other non-`CANCELLED` meetings of the same body, in this order. The **venue conflict** is checked first: the occupancy interval of a meeting on its venue runs from thirty minutes before its `scheduled_start` up to but not including its `scheduled_end` — the leading thirty minutes are a setup buffer, and the interval is half-open at its end. Two meetings sharing a `venue_id` conflict when the new meeting's buffered start falls before the other's buffered end and the other's buffered start falls before the new meeting's buffered end; such a collision is rejected with `ERR_VENUE_CONFLICT`. Because of the setup buffer, two back-to-back meetings in the same room still collide. The **presiding conflict** is checked second: the presiding interval of a meeting runs from its `scheduled_start` through its `scheduled_end` with both endpoints included (unbuffered and closed). Two meetings sharing a `presiding_member_id` conflict when the new meeting's start is at or before the other's end and the other's start is at or before the new meeting's end; such a collision is rejected with `ERR_PRESIDING_CONFLICT`. Because this interval is closed, two adjacent meetings that share only a single endpoint instant still collide for the presiding member.

### 3.3. Notice, Convening, and Adjournment

A meeting moves through its lifecycle dimension `SCHEDULED → NOTICED → IN_SESSION → ADJOURNED`, with `CANCELLED` reachable from `SCHEDULED`, `NOTICED`, or `IN_SESSION`. The `Clerk` posts statutory notice, advancing `SCHEDULED → NOTICED` and supplying a `notice_channel` of `WEBSITE`, `BULLETIN`, or `NEWSPAPER`; the channel is required for this transition. Posting stamps `notice_posted_at` to the current logical clock, records the channel, and computes `notice_lead_hours` as the number of hours between `notice_posted_at` and `scheduled_start` — that is, the difference `scheduled_start` minus `notice_posted_at` expressed in hours, kept as an exact, possibly fractional, hour count and not rounded. A clerk may re-post an amended notice while already `NOTICED` (a `NOTICED → NOTICED` self-transition), which again requires a `notice_channel` and recomputes `notice_posted_at` and `notice_lead_hours` against the new clock instant, resetting the lead-time clock.

Convening advances `NOTICED → IN_SESSION` and is performed by the `BodyMember` who is the meeting's presiding officer, supplying `present_member_ids`, the list of members recorded present. Three preconditions apply: the acting member's `X-User-ID` must equal the meeting's `presiding_member_id`, else `ERR_NOT_PRESIDING_OFFICER`; the meeting's `notice_lead_hours` must be at least the statutory minimum for its `meeting_type`, else `ERR_NOTICE_NONCOMPLIANT`; and the count of `present_member_ids` must be at least the body's `quorum_size`, else `ERR_QUORUM_NOT_MET`. The statutory minimums are 72 hours for a `REGULAR` meeting, 24 hours for a `SPECIAL` meeting, and 1 hour for an `EMERGENCY` meeting, and the comparison is inclusive — a lead time exactly equal to the minimum complies. On convening, the server stores `present_member_ids` and sets the computed `quorum_met` true (it is true whenever the number of present members is at least the quorum size).

The presiding officer adjourns by advancing `IN_SESSION → ADJOURNED`. Adjournment requires that the acting member be the presiding officer and that no `Motion` under any agenda item remains `OPEN`, else `ERR_OPEN_MOTIONS_EXIST`. Adjournment cascades: every `AgendaItem` still `OPEN` moves to `CLOSED`, and every `SpeakerSlip` still `QUEUED` or `CALLED` moves to `EXPIRED`.

Cancellation is a clerk action available from `SCHEDULED`, `NOTICED`, or `IN_SESSION` with no additional precondition. Cancelling a meeting cascades to every non-terminal `AgendaItem`, moving it to `CANCELLED`; and because an agenda item's own cancellation voids its motions and withdraws its speaker slips, cancelling an in-session meeting is a depth-three cascade — the meeting cancels its items, each cancelled item voids its motions and withdraws its slips.

### 3.4. Agenda Items, Public Comment, and the Speaker Queue

A `Clerk` publishes the agenda by adding **agenda items** to a meeting; the server stamps the owning meeting on the item's `meeting_id`. Each item carries a `title`, a `sequence` of at least 1 giving its order, an `item_type` of `ACTION`, `DISCUSSION`, or `CONSENT` (defaulting to `DISCUSSION`), and a `public_comment_enabled` flag (defaulting to true) governing whether the public may sign up to speak on it. A new item starts `PENDING`; its lifecycle is `PENDING → OPEN → CLOSED`, with `CANCELLED` reachable by cascade. The presiding `BodyMember` opens an item `PENDING → OPEN`, which requires that the acting member be the presiding officer and that the parent meeting be `IN_SESSION`, else `ERR_MEETING_NOT_IN_SESSION`. Only an `ACTION` item may carry motions; moving a motion under a non-`ACTION` item is rejected with `ERR_ITEM_NOT_ACTIONABLE`. The presiding officer closes an item `OPEN → CLOSED`, which requires the presiding role and that no motion under the item remain `OPEN` (`ERR_OPEN_MOTIONS_EXIST`); closing cascades every `QUEUED` or `CALLED` speaker slip under the item to `EXPIRED`.

A member of the public signs up to speak by creating a **speaker slip** on an item, supplying their own `requester_id`, a `speaker_name` for the podium display, and an optional `allotted_seconds` that defaults to 180. The server records the item on the slip's `agenda_item_id`; a motion likewise records its item on the motion's `agenda_item_id`. The `requester_id` must equal the acting requester's `X-User-ID`. Sign-up is refused with `ERR_PUBLIC_COMMENT_DISABLED` if the item's `public_comment_enabled` is false. Each item enforces an aggregate comment cap of 1800 seconds: summing the `allotted_seconds` of the slips already on the item whose status is `QUEUED`, `CALLED`, or `SPOKEN`, if adding the new slip's `allotted_seconds` would make that sum strictly exceed 1800 seconds, the sign-up is rejected with `ERR_COMMENT_CAP_EXCEEDED`. A new slip starts `QUEUED`, and its `position` is its 1-based rank by `created_at` ascending among the non-withdrawn slips on the item.

The presiding officer runs the queue. Calling a speaker advances `QUEUED → CALLED` and requires the presiding role, that the parent agenda item be `OPEN` (else `ERR_INVALID_STATE`), and that no other slip on the same item is currently `CALLED` (else `ERR_SPEAKER_ALREADY_ACTIVE`); calling stamps `called_at` to the logical clock. A called speaker is then marked `CALLED → SPOKEN` or `CALLED → YIELDED` by the presiding officer, with no further precondition. The signer may withdraw their own slip while it is `QUEUED`, advancing `QUEUED → WITHDRAWN`; this requires that the acting requester own the slip (`ERR_NOT_RESOURCE_OWNER`) and frees that slip's `allotted_seconds` from the item's comment-cap total. Slips also reach `EXPIRED` by cascade when the item closes or the meeting adjourns, and reach `WITHDRAWN` by cascade when the item is cancelled.

### 3.5. Motions and the Roll-Call Vote

On an `ACTION` item, a `BodyMember` moves a **motion**, supplying the motion `text`, a `moved_by_member_id`, a `seconded_by_member_id`, and an optional `vote_threshold` of `SIMPLE` or `ABSOLUTE` (defaulting to `SIMPLE`). The mover and seconder must each be present members of the meeting — each must appear in the meeting's `present_member_ids`, else `ERR_MEMBER_NOT_PRESENT` — and the seconder must be distinct from the mover, else `ERR_MOVER_SECONDER_SAME`. A new motion starts `DRAFT`. Its lifecycle is cyclic: `DRAFT → OPEN`, `OPEN → CARRIED`, `OPEN → FAILED`, `OPEN → TABLED`, and `TABLED → OPEN` for reconsideration, with `VOIDED` reachable by cascade.

The presiding officer opens voting `DRAFT → OPEN`, which requires the presiding role, that the parent agenda item be `OPEN` (else `ERR_INVALID_STATE`), and that the parent meeting be `IN_SESSION` (else `ERR_MEETING_NOT_IN_SESSION`). While a motion is `OPEN`, members cast roll-call ballots. A ballot supplies the voter's `member_id` and a `value` of `YEA`, `NAY`, `ABSTAIN`, or `RECUSED`; the voter must be a present member, else `ERR_MEMBER_NOT_PRESENT`. Ballots are upserted one per member — re-casting replaces that member's prior ballot rather than adding a second. Every ballot recomputes the tally: `yea_count`, `nay_count`, `abstain_count`, and `recused_count` are the counts of ballots with each value, and `ballot_count` is their sum. Until the motion closes its `outcome` is `PENDING`.

The presiding officer closes voting, and the server computes the branch from the tally rather than the client choosing it: closing an `OPEN` motion moves it to `CARRIED` or `FAILED` according to the motion's `vote_threshold`. Under the `SIMPLE` variant the motion carries when `yea_count` is strictly greater than `nay_count`, and fails otherwise; abstentions and recusals are excluded from this comparison. Under the `ABSOLUTE` variant the motion carries when twice `yea_count` is strictly greater than the body's `seat_count` — a majority of the full authorized membership — and fails otherwise; here abstentions and recusals effectively count against passage because they are not yeas. The presiding officer may instead table an open motion `OPEN → TABLED`, then later reconsider it `TABLED → OPEN` (which again requires the meeting be `IN_SESSION`); reconsideration retains the existing ballots. When an agenda item is cancelled, each of its motions in `DRAFT`, `OPEN`, or `TABLED` is voided, and voiding clears that motion's `ballots` to an empty list.

### 3.6. Minutes and the Vote Record

Minutes advance on a **parallel dimension** of the meeting, `minutes_status`, independent of the lifecycle dimension but gated by it. The values are `NONE → DRAFT → APPROVED → AMENDED`, and the amendment cycle closes with `AMENDED → APPROVED`. A `Clerk` drafts minutes `NONE → DRAFT`, supplying `minutes_text`; this is permitted only when the lifecycle `status` is `ADJOURNED`, else `ERR_INVALID_STATE`. The presiding `BodyMember` approves `DRAFT → APPROVED`, which requires the acting member be the presiding officer and stamps `minutes_approved_at` to the logical clock. A clerk amends approved minutes `APPROVED → AMENDED`, supplying replacement `minutes_text` and clearing `minutes_approved_at` back to null. The presiding officer re-approves `AMENDED → APPROVED`, again stamping `minutes_approved_at`. Because this dimension is orthogonal, a meeting may sit at `ADJOURNED` on its lifecycle while its minutes move independently through drafting and approval.

### 3.7. Records Request Intake

A member of the public self-registers as a `Requester`, supplying a `full_name`, an `email`, and an optional `organization` (defaulting to null); this is the one write an `Anonymous` caller may perform. A registered requester submits a **records request** addressed to a body, supplying their own `requester_id` (which must equal their `X-User-ID`), the `body_id`, a `subject`, a `description` of the records sought, and an `estimated_page_count` of at least 0. On submission the server stamps `submitted_at` to the logical clock, sets `status` to `RECEIVED`, and computes two derived values.

The **response deadline** advances ten business days from the calendar date of `submitted_at`. Beginning from the submission date (the submission day itself excluded), the server steps forward one calendar day at a time, decrementing a counter only on days that fall Monday through Friday, until ten business days have elapsed; weekends are skipped and no holiday calendar applies. The resulting date is pinned to the instant `23:59:59Z`, and that instant is `response_deadline`. For example, a request submitted `2026-06-01T09:00:00Z`, a Monday, yields a deadline of `2026-06-15T23:59:59Z`.

The **estimated fee** is a forward-looking copy fee over the requester's declared page estimate, with labor excluded because no review effort is known at intake. It is computed by the copy-fee schedule applied to `estimated_page_count` and stored in `estimated_fee_cents`. The copy-fee schedule works as follows: the first 50 pages are free; of the billable pages beyond that free allowance, the first 450 pages (that is, pages up to a running total of 500) are charged 15 cents each, and every page beyond a running total of 500 is charged 10 cents each. Concretely, billable pages are the page count minus 50 but not less than 0; the tier-one portion is those billable pages capped at 450; the tier-two portion is any billable pages beyond 450; and the copy fee in cents is the tier-one portion times 15 plus the tier-two portion times 10. Copy fees are exact integer cents. At intake `assessed_fee_cents`, `amount_waived_cents`, `amount_paid_cents`, and `fee_balance_cents` all stand at 0, and `decision` is `NONE`.

### 3.8. Review, Documents, Determination, and Fee Settlement

A `RecordsOfficer` opens review by advancing the request `RECEIVED → UNDER_REVIEW`. Under review, the officer attaches **responsive documents**, each recording its owning request on the document's `request_id` and supplying a `title`, a `page_count` of at least 0, `review_minutes` of at least 0 spent reviewing and redacting it, an optional `exemption_code` of `NONE`, `PRIVACY`, `DELIBERATIVE`, `SECURITY`, or `MEDICAL` (defaulting to `NONE`), and an optional `retention_series` of `PERMANENT`, `FISCAL`, `ADMIN`, or `TRANSITORY` (defaulting to `ADMIN`). Attaching a document is permitted only while the parent request is `UNDER_REVIEW`, else `ERR_DOCUMENT_REQUEST_NOT_UNDER_REVIEW`, and it increments the parent request's `version` — the fact that makes determinations version-sensitive. A new document starts `IDENTIFIED`.

Each document is worked through its own lifecycle. The officer marks a document `IDENTIFIED → REVIEWED` (permitted only while the parent request is `UNDER_REVIEW`, else `ERR_DOCUMENT_REQUEST_NOT_UNDER_REVIEW`). From `REVIEWED` it may go to `RELEASED` with no further precondition, or to `REDACTED` or `EXEMPT`, each of which requires an `exemption_code` other than `NONE` (a redaction or full withholding needs an exemption basis), else `ERR_VALIDATION`. The computed `billable_pages` equals the document's `page_count` when its status is `RELEASED` or `REDACTED`, and 0 when it is `EXEMPT` or `CANCELLED` — withheld pages are not copied.

The officer issues a **determination** advancing the request from `UNDER_REVIEW` to `GRANTED`, `PARTIALLY_GRANTED`, or `DENIED`, supplying the `decision`, the required `expected_records_request_version`, and an optional `waive_fee_cents` (defaulting to 0 when omitted and required to be at least 0). The waiver may not exceed the computed assessed fee, else `ERR_WAIVER_EXCEEDS_FEE`; and the version must match the request's current `version` under §2.8, else `ERR_STALE_VERSION` — the waiver check is evaluated before the version match, per §2.10. The determination computes `assessed_fee_cents` as the copy fee over the actual released and redacted pages plus the labor fee, records `amount_waived_cents` from the waiver, recomputes `fee_balance_cents`, records `determined_by_user_id` and `determined_at`, and sets `decision` and `status` to match the branch.

The **assessed copy fee** applies the same copy-fee schedule described in §3.7, but over the sum of `page_count` across documents whose status is `RELEASED` or `REDACTED`; exempt and cancelled documents contribute zero pages. The **labor fee** is computed in a pinned order: for each document whose status is `RELEASED`, `REDACTED`, or `EXEMPT` — labor is billed even for withheld documents because the review effort was expended — round that document's `review_minutes` up to the next whole 15-minute increment; sum those per-document rounded minutes; subtract a free allowance of 30 minutes but not below 0; convert the remaining chargeable minutes to hours by dividing by 60; multiply by the labor rate of 2500 cents per hour; and round the result half-up to whole cents. The rounding is per-document-then-sum; summing raw minutes first and rounding once would give a different, incorrect result. The assessed fee is the assessed copy fee plus this labor fee, and the balance is the assessed fee minus the waiver minus payments received so far.

A requester pays against the balance, supplying an `amount_cents` of at least 0; each payment adds to `amount_paid_cents` and recomputes `fee_balance_cents`. The officer closes a `GRANTED` or `PARTIALLY_GRANTED` request by advancing it to `CLOSED`, but only when `fee_balance_cents` is exactly 0; a positive balance blocks closing with `ERR_FEE_OUTSTANDING` (this fiscal check is applied after the state check). A `DENIED` request may be closed with no fee precondition. A requester may withdraw their own request (ownership enforced, else `ERR_NOT_RESOURCE_OWNER`): withdrawing from `RECEIVED` advances it to `WITHDRAWN` and cascades every non-`DISPOSED` document to `CANCELLED`; withdrawing from `UNDER_REVIEW` additionally resets `assessed_fee_cents` and `fee_balance_cents` to 0 along with cancelling its documents.

### 3.9. Appeals, Remand, Reopening, and Retention

When a determination denies or only partially grants a request, the requester may file an **appeal** that records its target on the appeal's `request_id`, supplying the `grounds`. An appeal may be filed only while the request is `DENIED` or `PARTIALLY_GRANTED`, else `ERR_REQUEST_NOT_DENIED`, and only within the appeal window — the logical clock must be at or before `determined_at` plus 30 days, else `ERR_APPEAL_WINDOW_CLOSED`. Filing stamps `filed_at` to the logical clock and starts the appeal at `FILED`.

An `AppealsOfficer` takes up the appeal `FILED → UNDER_REVIEW`, which enforces segregation of duties: the acting officer's `X-User-ID` must differ from the request's `determined_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; taking it up records `decided_by_user_id`. From `UNDER_REVIEW` the appeal resolves to one of three terminal outcomes, each with a distinct effect. Upholding (`UNDER_REVIEW → UPHELD`) sets the appeal `decision` to `UPHELD` and leaves the request unchanged — the denial stands. Overturning (`UNDER_REVIEW → OVERTURNED`) sets the decision to `OVERTURNED` and cascades the request — whether it was `DENIED` or `PARTIALLY_GRANTED` — to `GRANTED`, recomputing the assessed fee over the request's currently `RELEASED` and `REDACTED` documents; the overturn changes no document statuses (unlike the remand branch). Remanding (`UNDER_REVIEW → REMANDED`) sets the decision to `REMANDED` and reopens the request: a `DENIED` or `PARTIALLY_GRANTED` request returns to `UNDER_REVIEW`, each of its `EXEMPT` documents returns to `REVIEWED` for re-review, its `decision` resets to `NONE`, and `determined_by_user_id` and `determined_at` are cleared — a depth-two cascade distinct from the overturn branch.

Finally, records are destroyed only after their retention schedule elapses. A `Clerk` or `RecordsOfficer` disposes a document by advancing a `RELEASED`, `REDACTED`, or `EXEMPT` document to `DISPOSED`, permitted only when the logical clock is at or after the document's `created_at` plus the retention period for its `retention_series`, else `ERR_RETENTION_NOT_ELAPSED`. Retention periods, measured in years of 365 days each, are 9999 years for `PERMANENT`, 7 years for `FISCAL`, 3 years for `ADMIN`, and 1 year for `TRANSITORY`; the comparison is inclusive at day resolution.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state transition, ballot cast, payment, and the logical-clock set — return `200 OK`. Reads return `200 OK`. Every transition endpoint takes a `to_status` field naming the target state (alongside any state-specific fields such as `notice_channel`, `present_member_ids`, or `minutes_text`).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Clerk |
| POST | `/public-bodies` | Create a governing body | Clerk |
| GET | `/public-bodies/{id}` | Read a governing body | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester |
| POST | `/public-bodies/{id}/members` | Add a member (seat) to the body | Clerk |
| GET | `/public-bodies/{id}/members` | List members of a body | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester |
| POST | `/public-bodies/{id}/venues` | Register a venue for the body | Clerk |
| GET | `/public-bodies/{id}/venues` | List venues of a body | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester |
| POST | `/public-bodies/{id}/meetings` | Schedule a meeting | Clerk |
| GET | `/meetings/{id}` | Read a meeting | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester, Anonymous |
| GET | `/public-bodies/{id}/meetings` | List meetings of a body | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester, Anonymous |
| POST | `/meetings/{id}/transition` | Advance the meeting lifecycle dimension | Clerk, BodyMember |
| POST | `/meetings/{id}/minutes` | Advance the meeting minutes dimension | Clerk, BodyMember |
| POST | `/meetings/{id}/agenda-items` | Add an agenda item | Clerk |
| GET | `/agenda-items/{id}` | Read an agenda item | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester, Anonymous |
| GET | `/meetings/{id}/agenda-items` | List agenda items of a meeting | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester, Anonymous |
| POST | `/agenda-items/{id}/transition` | Open or close an agenda item | BodyMember |
| POST | `/agenda-items/{id}/speaker-slips` | Sign up to speak on an item | Requester |
| GET | `/agenda-items/{id}/speaker-slips` | List speaker slips on an item | Clerk, BodyMember, Requester, Anonymous |
| POST | `/speaker-slips/{id}/transition` | Call/mark-spoken/yield or withdraw a slip | BodyMember, Requester |
| POST | `/agenda-items/{id}/motions` | Move a motion on an ACTION item | BodyMember |
| GET | `/agenda-items/{id}/motions` | List motions on an item | Clerk, RecordsOfficer, AppealsOfficer, BodyMember, Requester, Anonymous |
| POST | `/motions/{id}/transition` | Open/close/table/reconsider a motion | BodyMember |
| POST | `/motions/{id}/votes` | Cast or re-cast a roll-call ballot | BodyMember |
| POST | `/requesters` | Self-register as a member of the public | Anonymous |
| POST | `/records-requests` | Submit a records request | Requester |
| GET | `/records-requests/{id}` | Read a records request | Clerk, RecordsOfficer, AppealsOfficer, Requester |
| GET | `/records-requests` | List records requests | Clerk, RecordsOfficer, AppealsOfficer, Requester |
| POST | `/records-requests/{id}/transition` | Move request lifecycle | RecordsOfficer, Requester |
| POST | `/records-requests/{id}/determination` | Issue a determination (OCC-guarded) | RecordsOfficer |
| POST | `/records-requests/{id}/payments` | Record a fee payment | Requester |
| POST | `/records-requests/{id}/documents` | Attach a responsive document | RecordsOfficer |
| GET | `/records-requests/{id}/documents` | List responsive documents of a request | Clerk, RecordsOfficer, AppealsOfficer, Requester |
| POST | `/records-requests/{rid}/documents/{id}/transition` | Advance a document | RecordsOfficer, Clerk |
| POST | `/records-requests/{id}/appeals` | File an appeal | Requester |
| GET | `/records-requests/{id}/appeals` | List appeals of a request | Clerk, RecordsOfficer, AppealsOfficer, Requester |
| POST | `/records-requests/{rid}/appeals/{id}/transition` | Decide an appeal | AppealsOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_PRESIDING_OFFICER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_MOVER_SECONDER_SAME` | 422 |
| `ERR_WAIVER_EXCEEDS_FEE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEETING_NOT_IN_SESSION` | 409 |
| `ERR_OPEN_MOTIONS_EXIST` | 409 |
| `ERR_ITEM_NOT_ACTIONABLE` | 409 |
| `ERR_MEMBER_NOT_PRESENT` | 409 |
| `ERR_PUBLIC_COMMENT_DISABLED` | 409 |
| `ERR_SPEAKER_ALREADY_ACTIVE` | 409 |
| `ERR_COMMENT_CAP_EXCEEDED` | 409 |
| `ERR_DOCUMENT_REQUEST_NOT_UNDER_REVIEW` | 409 |
| `ERR_REQUEST_NOT_DENIED` | 409 |
| `ERR_NOTICE_NONCOMPLIANT` | 409 |
| `ERR_QUORUM_NOT_MET` | 409 |
| `ERR_VENUE_CONFLICT` | 409 |
| `ERR_PRESIDING_CONFLICT` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_RETENTION_NOT_ELAPSED` | 409 |
| `ERR_FEE_OUTSTANDING` | 409 |
