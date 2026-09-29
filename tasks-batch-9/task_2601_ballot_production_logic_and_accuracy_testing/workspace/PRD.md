# Ballot Production and Logic & Accuracy Testing API — Product Requirements Document

## 1. Introduction

A county elections office lives or dies by the paper trail. Between the close of candidate filing and the certification of results, the office must certify a contest slate, fix the printed order of every name on every ballot face, produce a distinct ballot style for each combination of precinct and overlapping district, prove that each style has been translated and produced in every legally required alternative format, buy the print run from a secure vendor, inspect what arrives, count what goes out to the polls, program and publicly test every tabulator, and finally account for every single sheet of paper it ever ordered. Today that work is coordinated across spreadsheets, vendor emails and paper custody logs, which means a single late change — a withdrawn contest, a disqualified candidate, a superseded style — silently invalidates artwork that is already on a press and test decks that are already built.

This document specifies the API that replaces that coordination. The service is the system of record for ballot production, equipment programming, public logic-and-accuracy testing, chain of custody and post-election ballot accountability. Its central design commitment is that **derived state is never stale**: whenever a contest, candidate, style, print job, lot or tabulator changes, every dependent count, invoice, readiness flag and custody total is recomputed inside the same request, and the response to the triggering request already shows the new values. Its second commitment is **segregation of duties**: the person who sends a ballot proof out cannot sign it off, and the technician who programs a tabulator cannot conduct its public test.

Because the service is used to drive tests as well as elections, all temporal evaluation reads a server-side logical clock rather than the host wall clock. Notice-lead computation, test-window admission, retention expiry, reconciliation timestamps, custody event timestamps and the `created_at` / `updated_at` fields on every resource all read that clock. The clock starts at `2026-08-01T00:00:00Z` when the service starts and is never advanced implicitly — only an explicit clock-setting request moves it, by supplying the target instant as `now`. That request is the one operation in the service that is not subject to role authentication, and it modifies no domain entity; it echoes the `now` value it accepted.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint: authentication, response shape, pagination, resource identity, phase gating, error precedence, concurrency control, the seal ledger, numeric precision and cascade semantics.

### 2.1. User and Role-Based Access Control

Every request other than the logical-clock request carries two headers: `X-User-ID`, naming the acting user, and `X-User-Role`, naming the capacity in which that user acts (the role header is also accepted under its short form `X-Role`; both spellings carry the same value). If the role header is absent, empty, or does not name one of the seven roles below, the request is rejected with `ERR_UNAUTHENTICATED`. If it names a recognized role that the target operation does not admit, the request is rejected with `ERR_UNAUTHORIZED`. Authorization is checked before anything else about the request is examined — before the payload schema, before the addressed resource is looked up.

The seven roles are `ElectionsDirector`, `BallotCoordinator`, `LanguageAccessCoordinator`, `PrintVendorRep`, `WarehouseCustodian`, `VotingSystemTechnician` and `PublicObserver`.

- An `ElectionsDirector` is the county elections official of record. It owns election phase advancement, contest and candidate certification, proof sign-off, press-proof approval, vendor registration and reconciliation.
- A `BallotCoordinator` builds the ballot: files contests and candidates, registers precincts, creates ballot styles, assigns styles to precincts, requests proofs and places print orders.
- A `LanguageAccessCoordinator` is the only role that may attest translation and alternative-format coverage, which is a precondition for sending a style out to proof.
- A `PrintVendorRep` acts for one registered print vendor and records secure deliveries.
- A `WarehouseCustodian` owns physical custody: quality inspection, lot receipt, issue, recall and return accounting, tabulator sealing, deployment and retention sealing.
- A `VotingSystemTechnician` registers and programs equipment, builds test decks, and schedules and conducts logic-and-accuracy testing.
- A `PublicObserver` may sign in to a scheduled logic-and-accuracy session and read anything; it may mutate nothing else.

Identity semantics differ by role, and they matter because several rules compare `X-User-ID` against a stored user identifier. When `X-User-Role` is `PrintVendorRep`, `X-User-ID` is the `id` of the acting `PrintVendor`; ownership checks compare the addressed print job's `vendor_id` to `X-User-ID`, and a representative of a different vendor recording a delivery is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `ElectionsDirector`, `BallotCoordinator`, `LanguageAccessCoordinator`, `WarehouseCustodian`, `VotingSystemTechnician` or `PublicObserver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server records it where a workflow requires an actor of record — as `proof_requested_by_user_id` and `proof_decided_by_user_id` on a ballot style, `approved_by_user_id` on a print job, `issued_by_user_id` on a ballot lot, `programmed_by_user_id` on a tabulator, `created_by_user_id` on a test deck, `conducted_by_user_id` on a logic-and-accuracy session, and `actor_user_id` together with `actor_role` on every custody event — and it compares that recorded value against `X-User-ID` on later requests, but it never resolves it to any entity's `id`. Custody events generated by a cascade rather than by a direct call record `actor_user_id` as the literal string `"system"`.

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

List endpoints accept pagination through query parameters. `limit` caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100. `offset` is the number of items to skip and defaults to 0. Both are echoed in the response envelope's `meta` object along with `total_count` (the number of items matching the request before the page window is applied) and `has_more` (true when items remain beyond the current window).

Unless a specific list states otherwise, list results are ordered by `created_at` ascending. Five lists carry a domain ordering instead, because election work is addressed by human-readable code rather than by insertion time:

- Precinct lists are ordered by `precinct_code` ascending.
- Ballot lot lists are ordered by `lot_code` ascending, then by `created_at` ascending. Because `lot_code` is unique within a print job, this ordering is total for the lots of a single job.
- Tabulator lists are ordered by `asset_tag` ascending.
- A contest's candidate list is ordered by `base_order_index` ascending, then by `created_at` ascending. Candidates with no assigned index sort after those that have one.
- The election's chain-of-custody ledger is ordered by `sequence_index` ascending.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource carries a server-minted `id` — a UUID string with no type prefix, never supplied by the client — and a `created_at` timestamp: an ISO 8601 UTC instant with exactly three fractional-second digits, read from the logical clock at creation. Every resource except a custody event additionally carries `updated_at`, refreshed to the current logical-clock instant on every mutation of that row, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row. A custody event is an append-only ledger line and is therefore deliberately impoverished: it has only `id` and `created_at`; it has no `updated_at` and no `version` field at all.

`version` is not merely informational. Two operations require the client to present the version it last observed (see Section 2.7), and a print job pins the ballot-style version it was ordered against, so any intervening bump to the style — a language certification, a proof decision, a lock, a superseding order — invalidates the press proof.

All temporal values are read from the logical clock: `certified_at`, `started_at`, `completed_at`, `last_reconciled_at`, `occurred_at`, `retention_until`, `created_at` and `updated_at`. Client-supplied instants — `election_date`, `filing_received_at`, `press_window_start`, `press_window_end`, `scheduled_start`, `scheduled_end`, `public_notice_posted_at` — must be parseable ISO 8601 UTC instants; anything else is a schema violation.

### 2.5. Election Phase Gating

An `Election` moves through six phases in order: `SETUP`, `CONTESTS_CERTIFIED`, `STYLES_LOCKED`, `DEPLOYED`, `POLLS_CLOSED` and `RECONCILED`. `RECONCILED` is terminal in the sense that no later phase exists, but reconciliation itself may be repeated while in that phase. Nearly every write is legal only in specific phases; attempting one outside its permitted set is rejected with `ERR_ELECTION_PHASE_INVALID`. The permitted sets are:

| Operation | Permitted election phases |
| --- | --- |
| Freeze contest and candidate ballot order | `SETUP` |
| Lock approved ballot styles | `CONTESTS_CERTIFIED` |
| Declare pre-election deployment complete | `STYLES_LOCKED` |
| Close the polls | `DEPLOYED` |
| Record a ballot-accountability reconciliation | `POLLS_CLOSED`, `RECONCILED` |
| File a contest | `SETUP` |
| File a candidate | `SETUP` |
| Certify a contest | `SETUP` |
| Withdraw a certified contest | `SETUP`, `CONTESTS_CERTIFIED`, `STYLES_LOCKED` |
| Disqualify a candidate | `SETUP`, `CONTESTS_CERTIFIED`, `STYLES_LOCKED` |
| Register a precinct | `SETUP`, `CONTESTS_CERTIFIED` |
| Assign a ballot style to a precinct | `CONTESTS_CERTIFIED`, `STYLES_LOCKED` |
| Create a ballot style | `SETUP`, `CONTESTS_CERTIFIED` |
| Record translation and format certifications | `SETUP`, `CONTESTS_CERTIFIED` |
| Send a style out for proofing | `CONTESTS_CERTIFIED`, and additionally `STYLES_LOCKED` when the style is being re-sent from `PROOF_REJECTED` |
| Decide a proof | `CONTESTS_CERTIFIED` |
| Place a print order | `CONTESTS_CERTIFIED`, `STYLES_LOCKED` |
| Approve a press proof | `CONTESTS_CERTIFIED`, `STYLES_LOCKED` |
| Receive a shipped lot | `STYLES_LOCKED`, `DEPLOYED` |
| Issue a lot to a precinct | `STYLES_LOCKED`, `DEPLOYED` |
| Recall an issued lot | `STYLES_LOCKED`, `DEPLOYED` |
| Record a lot's return counts | `DEPLOYED`, `POLLS_CLOSED` |
| Register a tabulator | `SETUP`, `CONTESTS_CERTIFIED`, `STYLES_LOCKED` |
| Program a tabulator | `STYLES_LOCKED` |
| Deploy a tabulator to a precinct | `STYLES_LOCKED` |
| Break a tabulator's deployment seal | `STYLES_LOCKED`, `DEPLOYED` |
| Build a test deck | `CONTESTS_CERTIFIED`, `STYLES_LOCKED` |
| Schedule a logic-and-accuracy session | `STYLES_LOCKED`, `DEPLOYED`, `POLLS_CLOSED` |

Seven writes are deliberately **not** phase-gated at all, because their timing is governed by their own state guards rather than by the election calendar: recording a quality inspection, recording a secure delivery, applying a retention seal, signing an observer in, starting a session, recording session results, and setting the logical clock. Every read is likewise ungated.

### 2.6. Error Precedence

Many requests violate more than one rule. The returned `error_id` is always the one belonging to the lowest-numbered rank below; ranks are evaluated in ascending order and the first violated rank decides the response.

| Rank | Check | Error |
| --- | --- | --- |
| 10 | The role header is absent, empty, or not one of the seven roles (every operation except setting the logical clock) | `ERR_UNAUTHENTICATED` |
| 20 | The role is recognized but the operation does not admit it (every operation except setting the logical clock) | `ERR_UNAUTHORIZED` |
| 30 | Payload or query-parameter schema violation | `ERR_INVALID_REQUEST` |
| 40 | The resource addressed by the path `id` does not exist | that entity's not-found error |
| 50 | A foreign key inside the payload does not resolve, or resolves to a row of another election | the referenced entity's not-found error |
| 60 | The presented version of the parent resource is not current | `ERR_STALE_ELECTION_VERSION` or `ERR_STALE_BALLOT_STYLE_VERSION` |
| 70 | A state guard fails: the owning election's phase, or the state of the contest, candidate, ballot style, print job, ballot lot, tabulator, test deck or session involved | `ERR_ELECTION_PHASE_INVALID`, `ERR_CONTEST_STATE_INVALID`, `ERR_CANDIDATE_STATE_INVALID`, `ERR_STYLE_STATE_INVALID`, `ERR_JOB_STATE_INVALID`, `ERR_LOT_STATE_INVALID`, `ERR_UNIT_STATE_INVALID`, `ERR_DECK_STATE_INVALID` or `ERR_SESSION_STATE_INVALID` |
| 80 | A segregation-of-duties rule is violated | `ERR_SEGREGATION_OF_DUTIES` |
| 90 | A referential business rule fails: vendor security, proof pinning, lot-to-precinct style match, unit-to-precinct style match, seal match at receipt, seal-number uniqueness | `ERR_VENDOR_NOT_SECURE`, `ERR_PROOF_VERSION_STALE`, `ERR_LOT_NOT_FOR_PRECINCT`, `ERR_UNIT_STYLE_MISMATCH`, `ERR_SEAL_MISMATCH`, `ERR_SEAL_NUMBER_DUPLICATE` |
| 100 | A temporal rule fails: public-notice lead, session admission window, tabulator test-window exclusivity, vendor press capacity | `ERR_PUBLIC_NOTICE_TOO_LATE`, `ERR_OUTSIDE_TEST_WINDOW`, `ERR_UNIT_TEST_WINDOW_CONFLICT`, `ERR_PRESS_CAPACITY_EXCEEDED` |
| 110 | A business constraint fails: observer minimum, language and format coverage, empty deck, off-style deck mark, deck capacity, ballot-order ambiguity, absence of certified contests, deployment readiness, final-canvass lot return, retention before reconciliation | `ERR_INSUFFICIENT_OBSERVERS`, `ERR_LANGUAGE_COVERAGE_INCOMPLETE`, `ERR_EMPTY_TEST_DECK`, `ERR_DECK_MARK_OFF_STYLE`, `ERR_DECK_MARKS_EXCEED_CAPACITY`, `ERR_BALLOT_ORDER_COLLISION`, `ERR_NO_CERTIFIED_CONTESTS`, `ERR_DEPLOYMENT_NOT_READY`, `ERR_LOTS_NOT_RETURNED`, `ERR_RETENTION_BEFORE_RECONCILIATION` |
| 120 | A quantity rule fails: ordered quantity below the precinct requirement, issue above receipt, return accounting above receipt | `ERR_QUANTITY_BELOW_REQUIREMENT`, `ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT`, `ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT` |

Three consequences of this ordering are worth calling out, because they are easy to get backwards. Starting a session that is already `IN_PROGRESS` after the logical clock has passed its `scheduled_end` returns `ERR_SESSION_STATE_INVALID` (rank 70), not `ERR_OUTSIDE_TEST_WINDOW` (rank 100). A technician who tries to conduct the test of a unit they programmed themselves, on a session that is also short of observers, receives `ERR_SEGREGATION_OF_DUTIES` (rank 80), not `ERR_INSUFFICIENT_OBSERVERS` (rank 110). Issuing a wrong-style lot in an over-large quantity returns `ERR_LOT_NOT_FOR_PRECINCT` (rank 90), not `ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT` (rank 120).

The state guards all share rank 70. When one request trips more than one of them, the guard that appears first in that operation's narrative in Section 3 decides the response; as a rule of thumb the owning election's phase is examined before any entity-level state.

A schema violation at rank 30 covers: a required field absent or null; a field of the wrong JSON type; an enum field carrying a value outside its declared set; a count, quantity or money field that is negative where its definition requires zero or more, or below one where its definition requires at least one; a window whose end is less than or equal to its start; a timestamp that is not an ISO 8601 UTC instant; a reported defect count larger than the sample size it was drawn from; and a delivery manifest that is empty or repeats a `lot_code`. Unknown extra fields are **not** a schema violation — they are ignored, and the response echoes only declared fields.

Rank 40 resolves to whichever not-found error belongs to the addressed collection: `ERR_ELECTION_NOT_FOUND`, `ERR_CONTEST_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_PRECINCT_NOT_FOUND`, `ERR_BALLOT_STYLE_NOT_FOUND`, `ERR_PRINT_VENDOR_NOT_FOUND`, `ERR_PRINT_JOB_NOT_FOUND`, `ERR_BALLOT_LOT_NOT_FOUND`, `ERR_TABULATOR_NOT_FOUND`, `ERR_TEST_DECK_NOT_FOUND` or `ERR_LA_SESSION_NOT_FOUND`.

### 2.7. Nested Path Resolution and Cross-Election Isolation

Where an operation addresses a resource through a parent collection, path segments are resolved strictly left to right: the parent is looked up first and its not-found error is returned before the child segment is even parsed. Rank 50 extends the same discipline to foreign keys carried inside a payload, on six operations: assigning a style to a precinct, placing a print order, issuing a lot to a precinct, programming a tabulator, deploying a tabulator and scheduling a logic-and-accuracy session. A payload foreign key that does not resolve, **or that resolves to a row belonging to a different election than the addressed resource**, is reported as that entity's not-found error rather than as a business error — a deliberate choice, so that one election's rows are never disclosed through the error channel of another. A test deck whose ballot style belongs to a different election than the tabulator being scheduled is `ERR_TEST_DECK_NOT_FOUND`; a precinct of another election is `ERR_PRECINCT_NOT_FOUND`; a style of another election is `ERR_BALLOT_STYLE_NOT_FOUND`.

### 2.8. Optimistic Concurrency Control

Exactly two writes are guarded by optimistic concurrency control, and in both cases the guarded write is legitimately repeatable, so no state precondition can stand in for the guard.

Placing a print order requires `expected_ballot_style_version`, a non-optional field carrying the `version` of the target `BallotStyle` that the client last observed. If it does not equal the style's current `version`, the order is rejected with `ERR_STALE_BALLOT_STYLE_VERSION` and HTTP 412. A second print order against the same style may legitimately supersede an earlier `PROOF_PENDING` order — a re-order at a different vendor or a different quantity — so the write is not blocked by the style's state; what the check catches is a client whose view of the style is out of date because a language certification, a proof decision, a lock or an earlier superseding order has advanced the style's `version` since it read it.

Recording a ballot-accountability reconciliation requires `expected_election_version`, a non-optional field carrying the `version` of the `Election` that the client last observed. If it does not equal the election's current `version`, the reconciliation is rejected with `ERR_STALE_ELECTION_VERSION` and HTTP 412. Reconciliation is intentionally repeatable — a `FINAL_CANVASS` snapshot supersedes a `PRELIMINARY` one on the same election — so a write that presents the version written by a prior reconciliation is stale rather than invalid, and rejecting it prevents a client from overwriting a snapshot it never saw.

No other operation accepts a version field. In particular, approving a press proof takes no version field: it compares the job's stored `style_version_at_creation` against the style's current `version` and answers with `ERR_PROOF_VERSION_STALE` (HTTP 409), which is a referential rule about the artwork on the press, not a concurrency guard on the caller.

### 2.9. Integer Quantities, Basis Points and Rounding

No floating-point value is ever stored or returned. Money is an integer number of cents in every field whose name ends in `_cents`. Rates are integer basis points — hundredths of a percent — in every field whose name ends in `_bp`. Ballot counts, mark counts, observer counts and indices are plain integers.

Three rounding disciplines are used, and which one applies is part of each rule, never a matter of taste:

- **Round half up** — to the nearest integer, with an exact half rounding away from zero — is used for every money and rate derivation: print subtotals, defect credits, defect rates in basis points.
- **Round up to the next whole integer** is used for the statutory ballot overage that sets a precinct's requirement, so the floor is never undershot.
- **Round down to the preceding whole integer** is used for every allowance and tolerance in ballot accounting, and for the whole-minute notice lead of a test session, so that an allowance is always the conservative (smaller) integer.

### 2.10. Cascade Semantics and Derived-Field Propagation

The service is immediately consistent: derived fields are recomputed inside the request that changes their inputs, and the response body of the triggering request already reflects the new values. A single call can therefore mutate many rows. Where a cascade is described in Section 3 as a numbered chain of hops, each hop is caused by the previous hop's mutation rather than by the original call, and every hop's mutation refreshes that row's `updated_at` and increments its `version` in the ordinary way. A cascade never asks the client to make a second call, and it never partially applies: either every hop lands or the request is rejected before the first one does.

Two properties hold across every cascade. First, terminal accounting is never rewritten: a ballot lot that has already reached `RETURNED` and contributed its counts to the accountability ledger is left untouched by an upstream rejection, even when its sibling lots are voided. Second, the money ledger and the ballot ledger are reversed independently: a rejected print job's invoice is zeroed and the election's committed print total reduced accordingly, while its `delivered_quantity` remains as shipped, because the pallets physically arrived.

### 2.11. The Seal Ledger and Chain of Custody

Physical custody is recorded in an append-only ledger. Each ledger line — a custody event — records `election_id`, a `subject_type` of either `TABULATOR_UNIT` or `BALLOT_LOT`, the `subject_id` of the tabulator or lot it concerns, an `event_type` drawn from `TRANSFER_OUT`, `RECEIPT`, `ISSUE`, `RECALL`, `RETURN`, `SEAL_APPLIED`, `SEAL_BROKEN`, `RETENTION_SEAL` and `VOID`, the subject's `from_state` and `to_state` as strings, the `seal_number` applied or broken (null for events that touch no seal), the `actor_role` and `actor_user_id` responsible, the `occurred_at` logical-clock instant, and a `sequence_index`: the one-based position of the line among the lines sharing the same `subject_id`, ordered by `occurred_at` ascending and then `created_at` ascending. The ledger is readable per election, optionally narrowed by `subject_type`, `subject_id` or `event_type`.

Two invariants ride on this ledger. Seal numbers are unique within an election while they are open: writing a `seal_number` that some other ballot lot or tabulator of the same election already holds is rejected with `ERR_SEAL_NUMBER_DUPLICATE`. And the election's `open_seal_count` is a conserved quantity — the number of `SEAL_APPLIED` and `RETENTION_SEAL` lines for the election minus the number of `SEAL_BROKEN` lines — so every compensating action returns the count to the value it had before the action it compensates.

### 2.12. Segregation of Duties

Three checks enforce that no single user can both create and bless the same artefact. The user who sent a ballot style out for proofing may not be the user who decides that proof. The technician who programmed a tabulator may not be the technician who conducts that unit's logic-and-accuracy session. And only the technician who actually conducted a session may record its results — a colleague entering the tallies is refused. All three answer with `ERR_SEGREGATION_OF_DUTIES`, and all three are evaluated at rank 80: after every state guard, before every referential, temporal and constraint rule.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Election and Certifying the Slate

An `ElectionsDirector` opens the production cycle by registering the election, supplying its official `name`, the `jurisdiction` that owns the run, and the `election_date` — the ISO 8601 UTC instant the polls open, which later anchors every retention window. Three further inputs are optional and carry defaults that matter downstream: `rotation_policy`, one of `NONE`, `PRECINCT_ROTATION` or `DISTRICT_ROTATION`, defaulting to `NONE`; `candidate_order_method`, either `ALPHABETICAL_BY_BALLOT_NAME` or `FILING_ORDER`, defaulting to `ALPHABETICAL_BY_BALLOT_NAME`; and `la_notice_hours`, the minimum whole hours of public notice required before a logic-and-accuracy session may open, which must be at least 1 and defaults to 48. A new election lands in `SETUP` with every derived figure at rest: `certified_contest_count` 0, `committed_print_cents` 0, `deployment_readiness` `BLOCKED`, `open_seal_count` 0, `total_ballots_received` 0, `total_ballots_issued` 0, `ballot_accountability_status` `PENDING`, `net_ballot_variance` 0, and both `reconciliation_basis` and `last_reconciled_at` null.

Contests are filed while the election is still in `SETUP`, by either an `ElectionsDirector` or a `BallotCoordinator`. A filing carries the `title` as it will be printed on the ballot face, a `contest_type` of `CANDIDATE` or `MEASURE`, the `district_code` whose voters see the contest, `seats_open` (at least 1, which later bounds test-deck mark capacity), and optionally `rotation_required`, defaulting to false. Only a `CANDIDATE` contest carries candidates and rotation. A newly filed contest is `DRAFT`, with `ballot_order_index` null, `certified_candidate_count` 0, and `certified_at` and `withdrawn_reason` both null.

Candidates are filed against a contest that is still `DRAFT` — a filing against a contest in any other state is refused with `ERR_CONTEST_STATE_INVALID` — and each carries the candidate's `full_name`, the `ballot_name` as printed, the `filing_received_at` instant at which the nomination filing was received, and optionally the `party_code` printed beside the ballot name. A filed candidate starts in `FILED`, with `base_order_index` and `disqualified_reason` null.

Certification of a contest is an `ElectionsDirector` action that moves it `DRAFT → CERTIFIED`, and it enforces four guards in this order. The election must be in `SETUP`, or the request fails with `ERR_ELECTION_PHASE_INVALID`. The contest itself must be `DRAFT`, or `ERR_CONTEST_STATE_INVALID`. A `MEASURE` contest is exempt from the candidate test and certifies with no candidates at all, but a `CANDIDATE` contest must have at least as many `FILED` candidates as it has `seats_open`, or the request fails with `ERR_CANDIDATE_STATE_INVALID` — a contest that cannot fill its seats is not certifiable. Finally, no other contest of the same election in `DRAFT` or `CERTIFIED` may share this contest's combination of `contest_type`, `district_code` and `title`; a duplicate is refused with `ERR_BALLOT_ORDER_COLLISION`. That combination is exactly what the printed contest order sorts on, so admitting a second one would leave the ballot face undefined. The guard deliberately sits on certification rather than on the later ordering pass: a duplicate is refused while it is still uncertified, and since no operation ever rewrites `contest_type`, `district_code` or `title`, a certified pair can never collide after the fact. A duplicate `DRAFT` contest therefore blocks its twin's certification with no remedy other than certifying neither, which is intended — either choice of printed order would be arbitrary.

Certification does real work beyond the status change. Every candidate of the contest still in `FILED` is promoted `FILED → CERTIFIED`, while candidates already `DISQUALIFIED` are left exactly as they are; `certified_candidate_count` is set to the number of candidates just certified and `certified_at` is stamped with the logical clock; each certified candidate's `base_order_index` is assigned on the certified basis described in Section 3.2; the election's `certified_contest_count` is recomputed; and `contest_count` is recomputed on every ballot style of the election whose district list contains this contest's `district_code`.

Freezing the ballot order is the `ElectionsDirector` action that advances the election `SETUP → CONTESTS_CERTIFIED`. It requires at least one `CERTIFIED` contest, or it fails with `ERR_NO_CERTIFIED_CONTESTS` — nothing is written and the election stays in `SETUP`. The pass considers only contests of the election whose status is `CERTIFIED`; contests in `DRAFT` or `WITHDRAWN` are excluded and keep `ballot_order_index` null. Those certified contests are sorted by four keys in order: first by contest type, with `CANDIDATE` contests ahead of `MEASURE` contests; then by `district_code` ascending as a byte-wise string comparison; then by `title` ascending, likewise byte-wise; and finally by `created_at` ascending as the deterministic tiebreak. A contest's `id` is never used as a sort key. Each contest then receives `ballot_order_index` equal to its one-based position in that sequence, so the indices are contiguous and start at 1. Because the collision guard already refused any duplicate combination, this pass always has a total order and never has to reject anything. In the same request every certified contest's candidates have `base_order_index` written on the certified basis — candidates still in `FILED` keep a null index — the election's `certified_contest_count` is recomputed, and the election's `version` is incremented. From this point contest filing is closed and proof requests are unlocked.

One asymmetry is deliberate. A contest withdrawn after the order was frozen has its `ballot_order_index` reset to null, and the surviving contests are **not** renumbered: the gap stays visible in the printed order of record, and every test deck already built against the affected styles is voided instead.

Alongside these writes the election exposes reads: the election itself with all derived ledger fields, its contests (optionally narrowed by `status`), a single contest, and a contest's candidates (also narrowable by `status`).

### 3.2. Candidate Ordering, Rotation, and the Two Layout Bases

The printed position of a candidate is never stored directly; it is derived, per (ballot style, contest) pair, from the candidate roster, the election's ordering method, the election's rotation policy and the style's rotation seed. The same roster can therefore yield two different printed orders depending on which **basis** the reader asks for, and this duality is intentional: the proof that was circulated to the parties must not be retroactively rewritten by a later disqualification.

The layout of a style may be read at any time, with the requested `basis` given as a query parameter that defaults to `CERTIFIED_BASIS`. On the `PROVISIONAL_BASIS` the candidate set is every candidate who ever filed — those in `FILED`, `CERTIFIED` and `DISQUALIFIED` alike. On the `CERTIFIED_BASIS` the candidate set is only those in `CERTIFIED`. The certified basis is also the basis used whenever the server itself assigns `base_order_index`: when the ballot order is frozen for the election, when a contest is certified, and when a candidate is disqualified.

Within a basis, the derivation runs as follows. Let the candidate set after the basis filter be the roster, and let its size be the rotation modulus. The roster is ordered according to the election's `candidate_order_method`: under `ALPHABETICAL_BY_BALLOT_NAME` by `ballot_name` ascending, then `filing_received_at` ascending, then `created_at` ascending; under `FILING_ORDER` by `filing_received_at` ascending, then `ballot_name` ascending, then `created_at` ascending. A candidate's `id` is never used as a tiebreak. Each candidate's `base_order_index` is its zero-based rank in that order.

A rotation group offset is then computed for the (style, contest) pair. When the election's `rotation_policy` is `NONE` the offset is zero. When the contest's `rotation_required` is false the offset is zero as well — a per-contest opt-out overrides the election policy for that contest alone, leaving the other contests on the same style rotating normally. When the policy is `PRECINCT_ROTATION` the offset is the style's `rotation_seed_index` reduced modulo the rotation modulus. When the policy is `DISTRICT_ROTATION` the offset is the sum of the style's `rotation_seed_index` and the contest's district offset, reduced modulo the rotation modulus, where the district offset is the zero-based position of the contest's `district_code` within the style's `district_codes` sorted ascending. If the contest's `district_code` is not a member of the style's `district_codes` the contest does not appear on that style at all and the layout omits it entirely.

Each candidate's `printed_position` is then the sum of its `base_order_index` and the offset, reduced modulo the rotation modulus, plus one — a one-based contiguous permutation of the positions from 1 to the roster size. The layout emits, for each contest, the list of `candidate_id`, `ballot_name`, `base_order_index` and `printed_position` in `printed_position` ascending order. Three boundaries deserve attention: when no candidate passes the basis filter the contest's candidate list is empty, no modulus is evaluated, and the offset is reported as zero; when exactly one candidate passes, every seed reduces to an offset of zero, so a single-candidate contest never rotates; and because the roster size differs between the two bases, the offset itself differs between them even for an identical seed — the two bases are not a relabelling of one another.

The layout response is a computed read rather than a stored row: it reports `style_id`, `style_code`, `revision`, the `basis` it was computed under, the election's `rotation_policy`, the style's `rotation_seed_index`, the style's `contest_count`, the total `candidate_count` across the contests it printed, and the `contests` array carrying the per-contest candidate lists.

Disqualification is an `ElectionsDirector` action carrying a `disqualified_reason`, permitted while the election is in `SETUP`, `CONTESTS_CERTIFIED` or `STYLES_LOCKED`. A candidate already in `DISQUALIFIED` cannot be disqualified again — that is `ERR_CANDIDATE_STATE_INVALID`. The path taken depends on the candidate's state. A `CERTIFIED` candidate may be disqualified only while its contest is `CERTIFIED`; a `FILED` candidate only while the election is still in `SETUP` and its contest is still `DRAFT`. A contest whose state does not match the requested path yields `ERR_CONTEST_STATE_INVALID`.

Disqualifying a `FILED` candidate is quiet: the candidate moves `FILED → DISQUALIFIED` and stores its `disqualified_reason`, and nothing cascades, because nothing had been frozen yet. Disqualifying a `CERTIFIED` candidate moves it `CERTIFIED → DISQUALIFIED` and starts a three-hop chain. In the first hop the candidate's `disqualified_reason` is stored, its `base_order_index` is cleared to null — a disqualified candidate holds no certified position — and the contest's `certified_candidate_count` is recomputed. In the second hop, because the contest's certified roster has shrunk, every surviving `CERTIFIED` sibling has its `base_order_index` recompacted on the certified basis, so the rotation modulus falls by one and the printed order of the whole contest can shift; this recompaction runs only once the ordering has been frozen, that is when the election is no longer in `SETUP`. In the third hop, because those indices moved, every test deck in `DRAFT` or `SEALED` whose expected marks reference the disqualified candidate, or whose ballot style covers this contest's district, transitions to `VOIDED` — its expectations no longer match the printed layout.

### 3.3. Precincts, the District Lattice, and Ballot Style Construction

Precincts are registered by an `ElectionsDirector` or a `BallotCoordinator` while the election is in `SETUP` or `CONTESTS_CERTIFIED`. Each carries a `precinct_code` unique within the election, a non-empty `district_codes` array of the district codes overlapping the precinct (de-duplicated, and compared as a set rather than as an ordered list), a `registered_voter_count` of zero or more, and the `polling_place` name that appears on delivery paperwork. Registration derives the precinct's statutory print requirement immediately: `required_ballot_quantity` is the registered voter count multiplied by 11 and divided by 10 — the statutory 110 percent floor — rounded **up** to the next whole ballot, so the floor is never undershot. A precinct with no registered voters therefore requires zero ballots, yet is still `NOT_READY` until a tabulator is deployed to it. A newly registered precinct has `assigned_style_id` null, `ballots_received` 0 and `deployment_status` `NOT_READY`, and its arrival forces a recomputation of the election's `deployment_readiness`, which a fresh `NOT_READY` precinct can only block.

A precinct's `ballots_received` is the sum of the issued quantities of the ballot lots currently pointing at it whose custody state is `ISSUED` or `RETURNED`. Lots sitting in the warehouse in `IN_TRANSIT` or `RECEIVED`, and lots that have been `VOIDED`, contribute nothing: paper in the building is not paper at the polling place. Continuing the earlier example, a precinct with 1750 registered voters requires 1925 ballots; a single issued lot of exactly 1925 satisfies the requirement on the boundary, while 1924 leaves the precinct `NOT_READY`.

Ballot styles are created by a `BallotCoordinator` while the election is in `SETUP` or `CONTESTS_CERTIFIED`. A style declares a `style_code` unique within the election, a non-empty and de-duplicated `district_codes` set naming the district combination it prints, a non-empty `language_set` of language codes that must be produced and must include `"EN"`, and a non-empty `required_formats` array that must include `"PAPER_STANDARD"` and whose members are drawn from the five recognized formats `"PAPER_STANDARD"`, `"LARGE_PRINT"`, `"AUDIO_BALLOT"`, `"BRAILLE_INDEX"` and `"ELECTRONIC_DISPLAY"`. Optionally it names a `supersedes_style_id`, the earlier style of the same election that this one replaces.

The relationship between contests, precincts and styles is a lattice resolved by district membership, not by a join table: a contest appears on a style exactly when the contest's `district_code` is a member of that style's `district_codes`, and a style fits a precinct when the office decides it does. A new style is born in `DRAFT` with `revision` 1, `proof_cycle_count` 0, empty `translated_languages` and `certified_formats` arrays, `precinct_count` 0, both `proof_requested_by_user_id` and `proof_decided_by_user_id` null, and `contest_count` derived from the count of the election's `CERTIFIED` contests whose `district_code` falls inside the new style's district set.

Creating a style also re-seeds rotation across the whole election. `rotation_seed_index` is recomputed for **every** ballot style of the election whose status is not `SUPERSEDED`, as the zero-based rank of `style_code` ascending among that set. Inserting a style whose `style_code` sorts below an existing one therefore shifts the rotation seed — and so the printed candidate order — of styles that already existed. The same recomputation runs whenever a style becomes `SUPERSEDED` and drops out of the ranked set.

When `supersedes_style_id` is present the named style must belong to the same election, or the creation fails with `ERR_BALLOT_STYLE_NOT_FOUND`. The named style then transitions to `SUPERSEDED` from whichever of `DRAFT`, `PROOF_REJECTED`, `APPROVED` or `LOCKED` it occupied, and four consequences follow together: every precinct whose `assigned_style_id` pointed at the old style is repointed to the new one and `precinct_count` is recomputed on both styles; `rotation_seed_index` is recomputed across the election's non-superseded styles; every print job of the old style still in `PROOF_PENDING` is rejected, with its invoice fields zeroed, its committed cost released from the election's total and its vendor's `active_job_count` recomputed; and every test deck of the old style in `DRAFT` or `SEALED` is voided. A `SUPERSEDED` style is never a legal target for any operation thereafter.

Pointing a precinct at a style is a `BallotCoordinator` action carrying `style_id`, legal while the election is in `CONTESTS_CERTIFIED` or `STYLES_LOCKED`. The named style must exist in the same election and must be `APPROVED` or already `LOCKED`; a `DRAFT`, `PROOFING`, `PROOF_REJECTED` or `SUPERSEDED` style is refused with `ERR_STYLE_STATE_INVALID`. This assignment must be in place before the styles of the election are locked, because that locking step requires every precinct to carry one; re-assignment remains legal after the lock, for example when a style has been superseded. The assignment writes `assigned_style_id`, recomputes the style's `precinct_count`, recomputes the precinct's `ballots_received` and `deployment_status`, and then recomputes the election's `deployment_readiness`.

Precincts may be listed with optional filters on `election_id`, `assigned_style_id` and `deployment_status`; styles may be listed with optional filters on `election_id`, `supersedes_style_id` and `status`, which is what makes the self-referential supersession chain traversable.

### 3.4. Language Access, Alternative Formats, and the Proofing Loop

Translation and accessibility coverage is attested by a `LanguageAccessCoordinator` and by no one else. The attestation supplies `translated_languages` and `certified_formats`, and both lists **replace** the style's stored lists wholesale rather than merging into them. It is accepted only while the election is in `SETUP` or `CONTESTS_CERTIFIED`, and only while the style itself is `DRAFT` or `PROOF_REJECTED`; a style in `PROOFING`, `APPROVED`, `LOCKED` or `SUPERSEDED` is refused with `ERR_STYLE_STATE_INVALID`. Each attestation bumps the style's `version`, which is precisely why a print order placed before the attestation can no longer be created against the stale version the client was holding.

Sending a style out for proofing is a `BallotCoordinator` action, and it is where coverage is enforced. Three guards apply. The election must be in `CONTESTS_CERTIFIED` — with the single widening that a style being re-sent from `PROOF_REJECTED` may also be re-sent while the election is in `STYLES_LOCKED`. The style must print at least one contest, that is its `contest_count` must be 1 or more, or the request fails with `ERR_STYLE_STATE_INVALID`; the same error answers an attempt to send a style that is not currently `DRAFT` or `PROOF_REJECTED`. And coverage must be complete: every member of `language_set` must appear in `translated_languages` and every member of `required_formats` must appear in `certified_formats`, or the request fails with `ERR_LANGUAGE_COVERAGE_INCOMPLETE`. Coverage is a containment test in one direction only — extra certified languages or formats beyond what the style requires are harmless.

A successful request moves the style to `PROOFING`, increments `proof_cycle_count` by one, records `proof_requested_by_user_id` as the calling `X-User-ID`, clears `proof_decided_by_user_id` back to null, and bumps the style's `version`. One further effect fires **only** on the loop path: when the style was in `PROOF_REJECTED` rather than `DRAFT`, `revision` is also incremented by one. The revision number therefore counts corrective cycles, while `proof_cycle_count` counts every trip through `PROOFING` including the first.

Deciding a proof is open to either an `ElectionsDirector` or a `BallotCoordinator`, requires the style to be `PROOFING` (otherwise `ERR_STYLE_STATE_INVALID`), and requires the election to be in `CONTESTS_CERTIFIED`. The deciding user's `X-User-ID` must differ from the style's `proof_requested_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. The payload carries a `decision` of either `APPROVE` or `REJECT`, and optionally a `decision_note`. The two branches diverge sharply and are specified with equal force:

- With `decision` `APPROVE` the style moves `PROOFING → APPROVED`, `proof_decided_by_user_id` is set to the deciding `X-User-ID`, and the style's `version` is bumped. Nothing else changes: `translated_languages`, `certified_formats`, `revision` and `proof_cycle_count` are all left as they stand.
- With `decision` `REJECT` the style moves `PROOFING → PROOF_REJECTED`, `proof_decided_by_user_id` is set to the deciding `X-User-ID`, and the style's `version` is bumped — and in addition `translated_languages` and `certified_formats` are both cleared to empty arrays, so re-translation and re-certification are required before the style can be sent out again, and every test deck of the style in `DRAFT` or `SEALED` transitions to `VOIDED`. `revision` is **not** touched by a rejection; only the subsequent re-request out of `PROOF_REJECTED` increments it.

The loop `PROOFING → PROOF_REJECTED → PROOFING` may run any number of times. A style also reaches `PROOF_REJECTED` without any human decision, from `PROOFING`, `APPROVED` or `LOCKED`, when a contest printed on it is withdrawn — the cascade of Section 3.5.

Locking the styles is the `ElectionsDirector` action that advances the election `CONTESTS_CERTIFIED → STYLES_LOCKED`, and it is the gate that opens equipment programming. Two preconditions apply: every precinct of the election must carry an `assigned_style_id`, or the request fails with `ERR_ELECTION_PHASE_INVALID`; and every style that some precinct points at must be `APPROVED`, or the request fails with `ERR_STYLE_STATE_INVALID`. Each such style then transitions `APPROVED → LOCKED` and has its `version` bumped. Styles that no precinct points at, and styles in `DRAFT`, `PROOFING` or `PROOF_REJECTED`, are left entirely untouched and their `version` does not move. Because locking bumps each locked style's `version`, a print job placed before the lock now pins a `style_version_at_creation` one behind the style, and its press proof can no longer be approved — the approval answers `ERR_PROOF_VERSION_STALE`. This is intended: print orders are meant to be placed against the locked artwork.

### 3.5. Contest Withdrawal: The Five-Hop Reversal

Withdrawing a contest is the most destructive operation in the service, and it is available to an `ElectionsDirector` while the election is in `SETUP`, `CONTESTS_CERTIFIED` or `STYLES_LOCKED`. The contest must be `CERTIFIED`; withdrawing a `DRAFT` or already-`WITHDRAWN` contest is `ERR_CONTEST_STATE_INVALID`. The request carries a `withdrawn_reason`. What follows is a five-hop transitive cascade in which each hop is caused by the previous hop's mutation, not by the withdrawal call itself.

**Hop 1 — the contest.** The contest moves `CERTIFIED → WITHDRAWN`, its `ballot_order_index` is cleared to null, the supplied `withdrawn_reason` is stored, and the election's `certified_contest_count` is recomputed. The remaining contests keep their indices; the gap is not closed.

**Hop 2 — the styles that printed it.** Because the contest is no longer certified, every ballot style of the election whose `district_codes` contains the withdrawn contest's `district_code` and whose status is `PROOFING`, `APPROVED` or `LOCKED` transitions to `PROOF_REJECTED`, has `contest_count` recomputed, and has `translated_languages` and `certified_formats` cleared to empty arrays. `proof_cycle_count` is **not** touched — only an explicit proof request increments it — and neither is `revision`. Styles in `DRAFT`, `PROOF_REJECTED` or `SUPERSEDED` are left alone. Every test deck of an affected style in `DRAFT` or `SEALED` is `VOIDED`.

**Hop 3 — the print jobs on those styles.** Because those styles left the approved set, every print job whose style is one of them and whose status is `PROOF_PENDING`, `PRINTING`, `QC_HOLD`, `QC_PASSED` or `DELIVERED` transitions to `REJECTED`. Its press window is released, so its vendor's `active_job_count` is recomputed; `invoice_subtotal_cents`, `defect_credit_cents`, `freight_cents` and `invoice_total_cents` are all set to 0; and the election's `committed_print_cents` is reduced by exactly the amount that job had previously committed — the `ESTIMATE` total for a job that had only been approved, the `FINAL` total for a job that had already been delivered. `delivered_quantity` is left as shipped, because the pallets physically arrived even though their artwork is no longer the artwork of record.

**Hop 4 — the lots of those jobs.** Because those jobs are rejected, every ballot lot of a rejected job whose custody state is `IN_TRANSIT`, `RECEIVED` or `ISSUED` transitions to `VOIDED`, with `issued_quantity` cleared to 0, `unused_quantity` restored to `quantity_received` and `precinct_id` and `issued_by_user_id` cleared to null, and a custody event of type `VOID` appended for each. A lot already in `RETURNED` is left completely alone: once its counts are in the accountability ledger, an upstream rejection does not rewrite the ledger. The election's `total_ballots_received` and `total_ballots_issued` are recomputed.

**Hop 5 — the precincts and the election.** Because those lots left `RECEIVED` and `ISSUED`, every precinct that had received ballots from them recomputes `ballots_received` — dropping to 0 when its only lots were voided — and therefore recomputes `deployment_status`, typically to `NOT_READY`; and because those precincts are no longer `READY`, the election's `deployment_readiness` is recomputed to `BLOCKED`.

The depth of this chain is why a delivered print run is not immune to a late contest withdrawal, and why the office is expected to treat certification as a commitment rather than a formality.

### 3.6. Print Vendors, Press Windows, Quality, and the Two Invoices

Vendors are registered by an `ElectionsDirector` with a legal `name`, a `press_line_count` of at least 1 (the aggregate number of jobs the vendor can run at any one instant), a `certified_secure` flag stating whether the vendor currently holds a secure-facility certification, and optionally a `status` of `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`. A new vendor starts with `quality_defect_rate_bp` 0 and `active_job_count` 0, where `active_job_count` is the number of that vendor's print jobs whose status is `PROOF_PENDING`, `PRINTING`, `QC_HOLD`, `QC_PASSED` or `DELIVERED`.

A `BallotCoordinator` places a print order against an approved or locked style. The order carries `vendor_id`, `style_id`, `quantity_ordered` (at least 1 ballot, covering the style across all its precincts), `unit_cost_cents_per_thousand` (the contract rate in cents per 1000 ballots, at least 1), a half-open press window given by `press_window_start` and `press_window_end` where the end must be strictly after the start, and the concurrency field `expected_ballot_style_version` described in Section 2.8. Guards fire in ascending rank: the vendor and the style must resolve, and a style of another election is `ERR_BALLOT_STYLE_NOT_FOUND`; the presented style version must be current, or `ERR_STALE_BALLOT_STYLE_VERSION`; the election must be in `CONTESTS_CERTIFIED` or `STYLES_LOCKED`; the style must be `APPROVED` or `LOCKED`, or `ERR_STYLE_STATE_INVALID`; the vendor must be `ACTIVE` **and** have `certified_secure` true, or `ERR_VENDOR_NOT_SECURE` — ballots are never printed outside a certified secure facility; the vendor's press capacity must accommodate the window; and the ordered quantity must cover the requirement.

Press capacity is an aggregate constraint, not a pairwise one. The proposed job conflicts when the number of the vendor's existing jobs in `PROOF_PENDING`, `PRINTING`, `QC_HOLD`, `QC_PASSED` or `DELIVERED` whose window intersects the proposed window is already equal to or greater than the vendor's `press_line_count`; the rejection is `ERR_PRESS_CAPACITY_EXCEEDED`. Both windows are half-open — they include their start instant and exclude their end instant — so a job that starts at exactly the instant another ends does not conflict with it. Because the limit counts overlaps collectively, each individual overlap can be perfectly legal while the collection is not: a two-line vendor accepts a second concurrent job and refuses the third.

The quantity rule is fiscal and sits at the very end of the order: `quantity_ordered` must be at least the sum of `required_ballot_quantity` across every precinct whose `assigned_style_id` is the ordered style, or the order is refused with `ERR_QUANTITY_BELOW_REQUIREMENT`. When no precinct has yet been assigned to the style the requirement is zero and any positive quantity passes.

A created job starts in `PROOF_PENDING`, copies `election_id` from the referenced style, pins `style_version_at_creation` to the style's `version` as observed and accepted, and begins with `sample_size` 0, `defect_count` 0, `defect_rate_bp` 0, `inspection_count` 0, `delivered_quantity` 0, `approved_by_user_id` null, `invoice_basis` null and all four invoice money fields at 0. The vendor's `active_job_count` is recomputed. Jobs are listable with optional filters on `election_id`, `vendor_id`, `style_id` and `status`.

Approving the press proof is an `ElectionsDirector` action that moves the job `PROOF_PENDING → PRINTING`. The job must be `PROOF_PENDING`, or `ERR_JOB_STATE_INVALID`; the election must be in `CONTESTS_CERTIFIED` or `STYLES_LOCKED`; the style must still be `APPROVED` or `LOCKED`, or `ERR_STYLE_STATE_INVALID`; the vendor must still be `ACTIVE` with `certified_secure` true, or `ERR_VENDOR_NOT_SECURE`; and the style's current `version` must still equal the job's pinned `style_version_at_creation`, or the approval fails with `ERR_PROOF_VERSION_STALE`, because the artwork moved after the job was placed and the proof on the vendor's press is no longer the artwork of record. On success `approved_by_user_id` records the approving `X-User-ID`, `invoice_basis` is set to `ESTIMATE`, the estimate invoice is written, and the election's `committed_print_cents` increases by the job's new `invoice_total_cents`.

**The estimate invoice** bills the order as a single line, because nothing has shipped yet. `invoice_subtotal_cents` is the ordered quantity multiplied by the contract rate and divided by 1000, rounded half up to a whole cent — one rounding for the whole order. `delivered_quantity` stays 0. The billing quantity for freight purposes is the ordered quantity. `defect_credit_cents` is 0, since no inspection has been recorded. `invoice_total_cents` is the subtotal plus freight minus the defect credit.

**Freight** is a whole-tier flat fee keyed on the billing quantity, not a marginal rate. A billing quantity of 50 000 ballots or fewer carries 45 000 cents; a billing quantity above 50 000 but no more than 200 000 carries 90 000 cents; anything above 200 000 carries 150 000 cents. The boundaries are inclusive at the top of each tier: exactly 50 000 stays in the first tier, and 50 001 moves to the second.

Quality inspection belongs to the `WarehouseCustodian`, is not gated on the election phase, and requires the job to be `PRINTING` or `QC_HOLD` — inspecting a `PROOF_PENDING`, `QC_PASSED`, `DELIVERED` or `REJECTED` job is `ERR_JOB_STATE_INVALID`. Each inspection supplies a `sample_size` of at least 1 and a `defect_count` of zero or more that must not exceed the sample size; violations of either bound are `ERR_INVALID_REQUEST`, which is also what guarantees the rate below never divides by zero. Sampling is **cumulative**, never per-call: `inspection_count` increases by one, the payload's sample size is added to the job's running `sample_size`, the payload's defect count is added to the running `defect_count`, and `defect_rate_bp` is re-derived as the running defect count multiplied by 10 000 and divided by the running sample size, rounded half up to whole basis points. A re-inspection therefore dilutes the earlier sample rather than replacing it.

The derived rate decides the branch, and the threshold comparison is inclusive: a rate of 150 basis points — one and a half percent — or higher moves the job to `QC_HOLD`, and anything strictly below releases it to `QC_PASSED`. A rate landing exactly on 150 holds the job; one basis point lower releases it. The branch is symmetric in both directions and in both starting states: a `PRINTING` job goes to `QC_PASSED` or to `QC_HOLD`; a `QC_HOLD` job re-inspected below the threshold is released to `QC_PASSED`, and re-inspected at or above the threshold stays in `QC_HOLD` as a self-transition, with `inspection_count` still increasing. Each inspection also re-derives the vendor's rolling `quality_defect_rate_bp` across all of that vendor's jobs that have been inspected at least once, as the sum of their defect counts multiplied by 10 000 and divided by the sum of their sample sizes, rounded half up; when no job of the vendor has been inspected the field is 0.

Delivery is recorded by the `PrintVendorRep` whose `X-User-ID` equals the job's `vendor_id` — any other vendor's representative is refused with `ERR_UNAUTHORIZED`. The job must be `QC_PASSED`, or `ERR_JOB_STATE_INVALID`. The payload carries `lots`, the delivery manifest: a non-empty list in which each entry declares a `lot_code`, a `quantity_shipped` of at least 1, and the tamper `seal_number` the vendor applied to that pallet. The manifest is applied atomically and there is no partial success. Every line is validated before any lot is created: an empty list, a `lot_code` repeated within the manifest, or a non-positive `quantity_shipped` is `ERR_INVALID_REQUEST`; a `seal_number` repeated within the manifest, or already held by any ballot lot or tabulator of the election, is `ERR_SEAL_NUMBER_DUPLICATE` — because the uniqueness check runs across every manifest line before the first lot exists, a seal repeated inside one manifest collides with itself and rejects the whole call. A rejected manifest creates no lot, appends no custody event, and leaves the job in `QC_PASSED` with `invoice_basis` null and the election's `committed_print_cents` unchanged.

An accepted manifest moves the job `QC_PASSED → DELIVERED` and creates one ballot lot per line, each in `IN_TRANSIT` with `lot_code`, `quantity_shipped` and `seal_number` copied from the line, `election_id` copied from the job, and every accounting figure at rest: `quantity_received` 0, `issued_quantity` 0, `unused_quantity` 0, `voted_quantity` 0, `spoiled_quantity` 0, `returned_unused_quantity` 0, `accounted_quantity` 0, `lot_variance` 0, and `precinct_id` and `issued_by_user_id` null. A custody event of type `TRANSFER_OUT` with `to_state` `IN_TRANSIT` is appended for each created lot. `delivered_quantity` becomes the sum of `quantity_shipped` across the created lots, and the invoice is rewritten on the final basis.

**The final invoice** differs from the estimate in rounding topology as well as in which components exist. `invoice_subtotal_cents` is computed lot by lot rather than in one line: the job's lots whose custody state is not `VOIDED` are taken in `lot_code` ascending order, each lot's shipped quantity is multiplied by the contract rate and divided by 1000 and **rounded half up to a whole cent individually**, and those per-lot amounts are then added together — round-then-sum, rather than the estimate's sum-then-round. `delivered_quantity` is the sum of the same lots' shipped quantities, and it is the billing quantity for the freight tier. `defect_credit_cents` is the final subtotal multiplied by the job's cumulative `defect_rate_bp` and divided by 10 000, rounded half up; a job delivered without any inspection has a rate of 0 and therefore no credit. `invoice_total_cents` is again the subtotal plus freight minus the defect credit, and `invoice_basis` becomes `FINAL`. Finally the election's `committed_print_cents` is adjusted by the difference between the new final total and the estimate total the job had previously contributed.

Two consequences of the per-lot rounding are expected rather than accidental. A job whose split into lots produces several fractional lines can bill slightly **less** than its estimate even when the delivered quantity exactly equals the ordered quantity. And a job delivered with no non-voided lot at all has a subtotal of 0, a delivered quantity of 0 and therefore a billing quantity of 0, which still falls inside the first freight tier, so its total is exactly the first-tier freight fee.

### 3.7. Ballot Lot Custody: Receipt, Issue, Recall, and Return

Every physical movement of paper is a `WarehouseCustodian` action, is legal only in the election phases listed in Section 2.5, and appends a line to the custody ledger.

Receipt verifies the seal. The lot must be `IN_TRANSIT`, or `ERR_LOT_STATE_INVALID`; the payload's `seal_number` must equal the `seal_number` the vendor declared for that lot in the manifest, or the receipt is refused with `ERR_SEAL_MISMATCH` — the seal on the pallet is not the seal that was shipped; and `quantity_received` must be at least 1. On success the lot moves `IN_TRANSIT → RECEIVED`, stores the counted `quantity_received`, sets `unused_quantity` equal to it (nothing has been issued yet), appends a custody event of type `RECEIPT` recording `from_state` `IN_TRANSIT`, `to_state` `RECEIVED` and the lot's seal, and forces the election's `total_ballots_received` to be recomputed as the sum of `quantity_received` over the election's lots in `RECEIVED`, `ISSUED` or `RETURNED`.

Issue sends counted paper to a polling place. The payload carries the target `precinct_id` and the `issue_quantity`. The lot must be `RECEIVED`, or `ERR_LOT_STATE_INVALID`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the precinct's `assigned_style_id` must be the ballot style of the lot's own print job, or the issue is refused with `ERR_LOT_NOT_FOR_PRECINCT` — a precinct may not be handed ballots printed for a different district combination; and `issue_quantity` must be at least 1 and no greater than the lot's `quantity_received`, with an excess reported as `ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT` and a value below 1 as a schema violation. On success the lot moves `RECEIVED → ISSUED`, stores `precinct_id` and `issued_quantity`, sets `unused_quantity` to the received quantity minus the issued quantity, records `issued_by_user_id` as the custodian's `X-User-ID`, appends a custody event of type `ISSUE`, and triggers the readiness chain: the precinct recomputes `ballots_received` and `deployment_status`, and the election recomputes `total_ballots_issued` — the sum of `issued_quantity` over its lots in `ISSUED` or `RETURNED` — and `deployment_readiness`.

Recall is the compensating action for issue, optionally carrying a `recall_reason`. The lot must be `ISSUED`; it moves `ISSUED → RECEIVED`, `issued_quantity` returns to 0, `unused_quantity` returns to the full `quantity_received`, `precinct_id` and `issued_by_user_id` are cleared to null, and a custody event of type `RECALL` is appended. The precinct that had held the paper recomputes `ballots_received` and `deployment_status`, and the election recomputes `total_ballots_issued` and `deployment_readiness`. Across an issue followed by a recall the conserved identity — received equals issued plus unused — is exactly restored.

Return accounting closes the lot. It is accepted while the election is `DEPLOYED` or `POLLS_CLOSED`, requires the lot to be `ISSUED`, and carries the precinct board's three counts: `voted_quantity`, `spoiled_quantity` and `returned_unused_quantity`. Their sum may not exceed the lot's `quantity_received`, or the return is refused with `ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT`. On success the lot moves `ISSUED → RETURNED`, stores the three counts, sets `accounted_quantity` to their sum, and sets `lot_variance` to the issued quantity minus the accounted quantity — the lot's own missing-ballot figure, which stays null until the lot is returned. A custody event of type `RETURN` is appended, and the election's `total_ballots_issued` is recomputed; the lot remains inside that sum, because a returned lot's ballots were still issued.

A lot can also leave the pipeline sideways. When its print job is rejected, a lot in `IN_TRANSIT`, `RECEIVED` or `ISSUED` transitions to `VOIDED` and a custody event of type `VOID` is appended; voiding out of `ISSUED` additionally clears `issued_quantity` to 0, restores `unused_quantity` to `quantity_received`, and clears `precinct_id` and `issued_by_user_id`, because the pallet is pulled back out of the field. The election's received and issued totals are recomputed, and any precinct that had held the paper recomputes `ballots_received` and `deployment_status` before the election recomputes `deployment_readiness`. A lot in `RETURNED` is never voided.

Lots may be read individually with their full accounting line, or listed with optional filters on `election_id`, `print_job_id`, `precinct_id` and `custody_state`.

### 3.8. Tabulators, Test Decks, and the Public Logic & Accuracy Test

A tabulator carries **two state axes that advance independently**. Its `program_status` — one of `UNPROGRAMMED`, `PROGRAMMED`, `LA_PASSED` and `LA_FAILED` — tracks what software and logic the machine holds and whether that logic has been proved correct. Its `custody_status` — one of `IN_VAULT`, `DEPLOYED`, `RETURNED` and `SEALED_RETENTION` — tracks where the machine physically is and whose seal is on it. Neither axis is a function of the other: a machine can be `LA_PASSED` and still `IN_VAULT`, and a machine can be pulled out of `DEPLOYED` while its programming axis is untouched. Only `SEALED_RETENTION` is terminal, and the programming axis has no terminal state at all — it is deliberately cyclic, so a unit that fails its test can be re-programmed and re-tested.

A `VotingSystemTechnician` intakes a unit into the vault while the election is in `SETUP`, `CONTESTS_CERTIFIED` or `STYLES_LOCKED`, supplying the `asset_tag` stencilled on the machine (unique within the election) and optionally the `firmware_version` observed at intake. The unit is created `UNPROGRAMMED` and `IN_VAULT`, with `precinct_id`, `programmed_style_id`, `seal_number` and `retention_until` null and `la_session_count` 0. Units are readable individually with both axes, or listable in ascending `asset_tag` order with optional filters on `election_id`, `precinct_id`, `programmed_style_id`, `program_status` and `custody_status`.

Programming is a `VotingSystemTechnician` action legal only while the election is `STYLES_LOCKED`. It carries the `style_id` to load and the `firmware_version` being installed. The referenced style must exist in the same election, or `ERR_BALLOT_STYLE_NOT_FOUND`; it must be `LOCKED` — an `APPROVED` but unlocked style is `ERR_STYLE_STATE_INVALID`, because a machine must never be programmed against artwork that can still change; and the unit's `program_status` must be `UNPROGRAMMED` or `LA_FAILED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — a deployed machine is not reprogrammed in the field. On success `programmed_style_id`, `firmware_version` and `programmed_by_user_id` are written, the last from the calling `X-User-ID`, and `program_status` becomes `PROGRAMMED`. Programming a unit that previously failed simply overwrites all three fields, closing the loop from `LA_FAILED` back through `PROGRAMMED` to `LA_PASSED`; the recorded programmer is whoever performed the *latest* programming, which is what the segregation-of-duties check below consults.

A test deck is the physical instrument of the test: a stack of pre-marked ballots whose correct tally is known in advance. A `VotingSystemTechnician` or `BallotCoordinator` builds a deck against an `APPROVED` or `LOCKED` style while the election is `CONTESTS_CERTIFIED` or `STYLES_LOCKED`, supplying a `deck_code` unique within the style, a `ballot_count`, a `blank_count`, an `overvote_count`, and `expected_marks` — an array of objects each naming a `contest_id`, a `candidate_id` and an integer `mark_count` of at least 1. Composition is validated as follows.

1. `ballot_count` below 1 is refused with `ERR_EMPTY_TEST_DECK`. A deck of zero ballots demonstrates nothing, and it would make every later comparison vacuous. This applies even when `expected_marks` is itself empty.
2. Every `(contest_id, candidate_id)` pair must be printable on the style: the contest must exist, must be `CERTIFIED`, and its `district_code` must be a member of the style's `district_codes`; the candidate must be a `CERTIFIED` candidate of that same contest. Any pair failing any part of this is `ERR_DECK_MARK_OFF_STYLE`.
3. `expected_total_marks` is derived as the sum of `mark_count` across `expected_marks`. The deck's mark capacity is `ballot_count` multiplied by 40, the number of usable mark lines on one ballot face. If `expected_total_marks` exceeds that capacity the deck is refused with `ERR_DECK_MARKS_EXCEED_CAPACITY`. The comparison is strict: a one-ballot deck declaring exactly 40 marks is accepted, and 41 is refused. `blank_count` and `overvote_count` are deliberately **not** charged against mark capacity — a blank ballot consumes a ballot, not a mark line.

An accepted deck is created in `DRAFT` with the derived `expected_total_marks` and `created_by_user_id` set to the builder's `X-User-ID`. Decks of a style are listable with an optional `status` filter. A deck's lifecycle is `DRAFT` → `SEALED` when a session starts on it, then `SEALED` → `CONSUMED` on a passing result or `SEALED` → `VOIDED` on a failing one; `CONSUMED` and `VOIDED` are both terminal, so a deck is a single-use instrument. A deck in `DRAFT` or `SEALED` is also voided from outside whenever the layout it was built against stops being authoritative — when its style enters `PROOF_REJECTED` or `SUPERSEDED`, or when a candidate printed on that style is disqualified after ordering was frozen. A voided deck's `expected_marks` no longer describe the printed ballot, so any session still holding it can no longer be started and answers `ERR_DECK_STATE_INVALID`.

Scheduling a session is a `VotingSystemTechnician` action legal while the election is `STYLES_LOCKED`, `DEPLOYED` or `POLLS_CLOSED` — the last because post-election audits are conducted after the polls close. The request names the `tabulator_id` under test, the `deck_id` to be fed into it, a `session_type` of either `PRE_ELECTION_PUBLIC` or `POST_ELECTION_AUDIT`, a `scheduled_start`, a `scheduled_end` strictly after it, and the `public_notice_posted_at` instant at which the statutory notice was published. Guards run in ascending rank: the unit must resolve, or `ERR_TABULATOR_NOT_FOUND`, and the deck must resolve, or `ERR_TEST_DECK_NOT_FOUND`, with a deck or unit from another election reported as not found rather than as a business error; the election phase must permit scheduling; the unit's `program_status` must be `PROGRAMMED` or `LA_PASSED`, or `ERR_UNIT_STATE_INVALID` — an `UNPROGRAMMED` or `LA_FAILED` unit has nothing to test; the deck's `status` must be `DRAFT`, or `ERR_DECK_STATE_INVALID`; and the unit's calendar must be free.

**Window exclusivity** is what makes the calendar check interesting. A tabulator can host exactly one session at a time, and the technician needs half an hour on each side of a session to mount and clear the deck. Each session therefore occupies the **closed** interval running from 30 minutes before its `scheduled_start` to 30 minutes after its `scheduled_end`. The proposed session conflicts when any other session on the same `tabulator_id` — in *any* status, including the terminal `PASSED` and `FAILED` — has a buffered interval that overlaps the proposed buffered interval; the refusal is `ERR_UNIT_TEST_WINDOW_CONFLICT`. Because the buffered intervals are closed, two sessions that merely touch at a buffered endpoint **do** conflict: a session ending at noon blocks a session starting at 13:00 exactly, since both buffered intervals contain 12:30. A session starting one minute later is accepted. Unlike press capacity, this is not a counting rule — the unit's capacity is one, so the first overlap is already fatal. That completed sessions still occupy the calendar is intentional: a machine's test history is a matter of record and the same slot is not reused.

An accepted session is created `SCHEDULED` with `observer_count` 0, an empty `observer_names` array, an empty `reported_marks` array, and `reported_blank_count`, `reported_overvote_count`, `discrepancy_count`, `conducted_by_user_id`, `started_at` and `completed_at` all null. `notice_lead_minutes` is derived once, at creation, as the whole minutes from `public_notice_posted_at` to `scheduled_start`, rounded down; a notice posted *after* the scheduled start yields a negative lead, which is retained as computed rather than clamped. Sessions are readable individually or listable with optional filters on `tabulator_id`, `deck_id`, `status` and `session_type`.

Observers sign in one at a time. Either a `VotingSystemTechnician` or a `PublicObserver` may register a person, supplying an `observer_name`; the session must still be `SCHEDULED`, or `ERR_SESSION_STATE_INVALID`. The name is appended to `observer_names` in registration order and `observer_count` is recomputed as that array's length. Sign-in is not phase-gated, and names are not de-duplicated: the count is a count of registrations.

Starting the test is where the public-accountability rules land. It is a `VotingSystemTechnician` action, not phase-gated, and its guards are evaluated in this order.

- The session must be `SCHEDULED`, or `ERR_SESSION_STATE_INVALID` (rank 70). This outranks the window rule, so calling start again on a session already `IN_PROGRESS` after the clock has passed `scheduled_end` answers `ERR_SESSION_STATE_INVALID`, not `ERR_OUTSIDE_TEST_WINDOW`.
- The unit's `program_status` must be `PROGRAMMED` or `LA_PASSED`, or `ERR_UNIT_STATE_INVALID`; and the deck must still be `DRAFT`, or `ERR_DECK_STATE_INVALID` (both rank 70). A deck voided between scheduling and start is caught here.
- The starting `X-User-ID` must **differ** from the unit's `programmed_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` (rank 80). The technician who programmed a machine may not conduct its public test. This rule outranks the observer minimum, so a self-test start that is *also* short of observers answers `ERR_SEGREGATION_OF_DUTIES`.
- `notice_lead_minutes` must be at least the election's `la_notice_hours` multiplied by 60, or `ERR_PUBLIC_NOTICE_TOO_LATE` (rank 100). The comparison is inclusive: notice posted exactly the required number of hours ahead is sufficient. Note that the lead was frozen at creation — re-posting a notice does not repair a late session.
- The logical clock must fall inside the admission window, the closed interval from 60 minutes before `scheduled_start` through `scheduled_end`; otherwise `ERR_OUTSIDE_TEST_WINDOW` (rank 100). Observers may be admitted up to an hour early, but the session may not open after its scheduled end. Both endpoints are inclusive.
- `observer_count` must meet the minimum for the session type, or `ERR_INSUFFICIENT_OBSERVERS` (rank 110): at least 2 for a `PRE_ELECTION_PUBLIC` session, at least 1 for a `POST_ELECTION_AUDIT`. The comparison is inclusive at the minimum.

On success the session moves `SCHEDULED → IN_PROGRESS`, `started_at` is stamped from the logical clock, `conducted_by_user_id` records the starting `X-User-ID`, and the referenced deck transitions `DRAFT → SEALED`, becoming immutable for the duration of the session.

Recording results closes the session. It is a `VotingSystemTechnician` action, not phase-gated, and requires the session to be `IN_PROGRESS`, or `ERR_SESSION_STATE_INVALID`. The recording `X-User-ID` must **equal** the session's `conducted_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` — results are entered by the technician who actually ran the test, not by a third party. Note the deliberate opposition between the two segregation checks on the same session: the starter must differ from the programmer, and the recorder must match the starter. The payload carries what the machine read off the deck: `reported_marks`, an array of `contest_id` / `candidate_id` / `mark_count` objects in the same shape as the deck's expectation, plus `reported_blank_count` and `reported_overvote_count`.

**The discrepancy count** is an absolute-deviation total, computed as follows. Take the key set consisting of the union of the `(contest_id, candidate_id)` pairs appearing in the deck's `expected_marks` and in the payload's `reported_marks`. Walking that key set in ascending `contest_id` then ascending `candidate_id` order, accumulate the absolute difference between the reported `mark_count` and the expected `mark_count` for each key, treating a key absent from either side as 0 on that side. To that mark total add the absolute difference between `reported_blank_count` and the deck's `blank_count`, and the absolute difference between `reported_overvote_count` and the deck's `overvote_count`. The result is `discrepancy_count`. Three consequences follow directly. A reported mark for a pair the deck never declared contributes its entire reported count, since the expected side is 0. Two offsetting errors do **not** cancel — one candidate over by 3 and another under by 3 gives 6, not 0, because absolute values are summed before totalling. And a tally that is perfectly correct candidate by candidate but reports the wrong number of blanks still fails. The deck's `expected_total_marks` is reported alongside the comparison but is not itself part of the deviation: a machine that reports the right grand total with the wrong distribution fails.

`reported_marks`, `reported_blank_count`, `reported_overvote_count`, `discrepancy_count` and `completed_at` are stored on every recording, pass or fail. Then the branch.

**A discrepancy of exactly zero passes.** The session moves `IN_PROGRESS → PASSED`, the deck moves `SEALED → CONSUMED`, the unit's `program_status` moves to `LA_PASSED`, `la_session_count` is recomputed as the number of sessions on that unit, and the readiness chain runs: the unit's precinct, if it has one, recomputes `deployment_status`, and the election recomputes `deployment_readiness`.

**Any non-zero discrepancy fails, and the failure cascades four hops deep.** Hop 1: the session moves `IN_PROGRESS → FAILED` and the deck moves `SEALED → VOIDED` — the deck must be rebuilt before the unit can be tested again. Hop 2: the unit's `program_status` moves to `LA_FAILED`, and this happens whether the unit was `PROGRAMMED` or already `LA_PASSED`, so a post-election audit failure demotes a machine that had previously passed; additionally, if the unit's `custody_status` is `DEPLOYED`, the custody axis reverts `DEPLOYED → IN_VAULT` with `seal_number` and `precinct_id` cleared, a custody event of type `SEAL_BROKEN` appended with `actor_user_id` of `"system"`, and the election's `open_seal_count` decremented. Hop 3: because the unit left `DEPLOYED`, the precinct it had been deployed to recomputes `deployment_status` and falls to `NOT_READY` — it no longer has a passed, deployed tabulator. Hop 4: because that precinct is no longer `READY`, the election's `deployment_readiness` is recomputed to `BLOCKED`, which in turn blocks the declaration of deployment with `ERR_DEPLOYMENT_NOT_READY`. All four hops complete inside the request that records the result, so the response body already shows the demoted state.

### 3.9. Deployment, Poll Close, and the Accountability Close-Out

Deploying a tabulator is a `WarehouseCustodian` action, legal only while the election is `STYLES_LOCKED`, carrying the target `precinct_id` and the `seal_number` being applied. Its guards, in ascending rank, are: the unit must resolve, or `ERR_TABULATOR_NOT_FOUND`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the unit's `program_status` must be `LA_PASSED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — an untested machine never leaves the vault; at least one ballot lot with that `precinct_id` must be in `ISSUED`, or `ERR_LOT_STATE_INVALID` — the machine does not travel ahead of the paper; the unit's `programmed_style_id` must equal the precinct's `assigned_style_id`, or `ERR_UNIT_STYLE_MISMATCH` — a machine programmed for one district combination cannot read another's ballots; and the `seal_number` must not already be held by any other ballot lot or tabulator of the election, or `ERR_SEAL_NUMBER_DUPLICATE`. On success the unit moves `IN_VAULT → DEPLOYED`, stores `precinct_id` and `seal_number`, appends a custody event of type `SEAL_APPLIED` with `from_state` `IN_VAULT` and `to_state` `DEPLOYED`, increments the election's `open_seal_count` by one, and re-derives the precinct's `deployment_status` and the election's `deployment_readiness`.

Breaking the seal is the exact compensating action. It is a `WarehouseCustodian` action legal while the election is `STYLES_LOCKED` or `DEPLOYED`, carries a free-text `reason`, and requires `custody_status` to be `DEPLOYED`, or `ERR_UNIT_STATE_INVALID`. The unit moves `DEPLOYED → IN_VAULT`, `seal_number` and `precinct_id` are cleared to null, a custody event of type `SEAL_BROKEN` is appended recording the seal that was broken, and `open_seal_count` is decremented — returning to exactly its pre-deploy value. The formerly referenced precinct recomputes `deployment_status` and the election recomputes `deployment_readiness`. The programming axis is untouched: the unit is still `LA_PASSED` and can be redeployed without retesting.

**Deployment readiness** is the constraint-propagation chain that ties paper and machines together, and it is re-derived eagerly inside any request that changes one of its inputs — every lot issue, recall, void and return, every tabulator deploy, seal break and poll-close recall, and every recorded test result. A precinct's `deployment_status` is `READY` when **both** of two conditions hold: its `ballots_received` is greater than or equal to its `required_ballot_quantity`, and at least one tabulator exists whose `precinct_id` is that precinct with `program_status` `LA_PASSED` **and** `custody_status` `DEPLOYED`. Otherwise it is `NOT_READY`. A machine that has passed its test but is still `IN_VAULT` does not make its precinct ready; deployment is what counts. The election's `deployment_readiness` is `READY` when the election has at least one precinct **and** every one of its precincts is `READY`; otherwise `BLOCKED`. An election with zero precincts is `BLOCKED`, not `READY` — the empty conjunction is deliberately not treated as satisfied, because an election with no polling places is not prepared.

Declaring deployment complete is an `ElectionsDirector` action legal only from `STYLES_LOCKED`, and it is refused with `ERR_DEPLOYMENT_NOT_READY` while `deployment_readiness` is `BLOCKED`. On success the election moves `STYLES_LOCKED → DEPLOYED`.

Closing the polls is an `ElectionsDirector` action legal only from `DEPLOYED`. Every tabulator of the election whose `custody_status` is `DEPLOYED` transitions `DEPLOYED → RETURNED`, **retaining** its `seal_number` — the seal stays intact through transport, so `open_seal_count` does not change at poll close — and a custody event of type `RETURN` is appended for each with `actor_user_id` of `"system"`. Each affected precinct recomputes `deployment_status`, which necessarily falls to `NOT_READY` since no unit is deployed any longer, and the election recomputes `deployment_readiness`, which necessarily becomes `BLOCKED`. The election's `status` becomes `POLLS_CLOSED`. Machines left `IN_VAULT` are untouched.

Reconciliation is the accountability close-out: an `ElectionsDirector` action legal from `POLLS_CLOSED` or from `RECONCILED`, so an election can be reconciled again on a firmer basis without leaving its terminal phase. The request carries the `basis` — either `PRELIMINARY` or `FINAL_CANVASS` — and `expected_election_version`, the optimistic-concurrency field of Section 2.8. Guards run in ascending rank: schema first, then existence, then the version check answering `ERR_STALE_ELECTION_VERSION`, then the phase check, and finally, only for a `FINAL_CANVASS` request, the completeness check: if any ballot lot of the election is still in `ISSUED`, the reconciliation is refused with `ERR_LOTS_NOT_RETURNED`. A final canvass cannot be certified while paper is still in the field.

**The accountability worksheet** is evaluated strictly in the following order, and the ordering matters because the two tier lookups key on different figures.

1. Collect the lots in scope. The `PRELIMINARY` basis reconciles everything currently in the field: lots whose `custody_state` is `ISSUED` or `RETURNED`. The `FINAL_CANVASS` basis reconciles only lots physically returned: `custody_state` equal to `RETURNED`. Lots in `IN_TRANSIT`, `RECEIVED` or `VOIDED` are out of scope under both bases; `lot_count` is the number of lots in scope.
2. `gross_issued` is the sum of `issued_quantity` over the lots in scope.
3. `allowance_bp` is the spoilage allowance in basis points, keyed on **gross**: 25 basis points when `gross_issued` is 5000 or fewer, otherwise 15 basis points. The larger elections receive the *smaller* proportional allowance.
4. `spoilage_credit` is `gross_issued` multiplied by `allowance_bp`, divided by 10 000, **rounded down**.
5. `net_issued` is `gross_issued` minus `spoilage_credit`.
6. `accounted` is the sum of `accounted_quantity` over the lots in scope, where each lot's `accounted_quantity` is its `voted_quantity` plus `spoiled_quantity` plus `returned_unused_quantity`. A lot still in `ISSUED` has not reported its counts, so it contributes 0 to `accounted` while contributing its full `issued_quantity` to `gross_issued`.
7. `gross_variance` is `gross_issued` minus `accounted` — the raw count of ballots not accounted for. `net_variance` is `gross_variance` minus `spoilage_credit` when `gross_variance` is strictly positive, and simply `gross_variance` when `gross_variance` is zero or negative. The asymmetry is deliberate: the allowance excuses *missing* ballots, not surplus ones, so an over-accounted election gets no relief and keeps its negative variance at full size.
8. `tolerance_bp` is the variance tolerance in basis points, keyed on **net**, not on gross: 200 basis points when `net_issued` is 5000 or fewer; 100 basis points when `net_issued` is greater than 5000 but no more than 20 000; and 50 basis points when `net_issued` is above 20 000.
9. `tolerance_ballots` is `net_issued` multiplied by `tolerance_bp`, divided by 10 000, **rounded down**.
10. `ballot_accountability_status` is `BALANCED` when the absolute value of `net_variance` is less than or equal to `tolerance_ballots`, and `OUT_OF_BALANCE` otherwise. A variance exactly equal to the tolerance is balanced; one ballot more is not.

Both tiered quantities round down, so both the allowance and the tolerance are always the conservative, smaller integer. Because step 3 keys on gross and step 8 keys on net, and step 4 has removed some ballots in between, an election sitting exactly on the gross tier edge lands in a different tolerance tier than a naive single-pass reading would predict: 5000 gross ballots take the 25-basis-point allowance and the resulting net figure falls strictly below 5000, still inside the first tolerance tier but no longer at its edge. Reconciling an election with nothing in scope is vacuously balanced: every figure is 0, and 0 is within a tolerance of 0. And the same election reconciled under the two bases can return two different statuses, precisely because a lot still `ISSUED` contributes its issued quantity without contributing any accounted quantity.

A reconciliation writes the worksheet's results onto the election: `total_ballots_issued` becomes `gross_issued`, `net_ballot_variance` becomes `net_variance`, `ballot_accountability_status` becomes the derived status, `reconciliation_basis` records the basis used, `last_reconciled_at` is stamped from the logical clock, `status` becomes `RECONCILED`, and `version` is bumped — which is why a client re-reconciling must read the election again to obtain a fresh `expected_election_version`.

The same worksheet is available as a pure computed read that mutates nothing, open to every role, and returning the whole line of intermediate figures rather than just the verdict: `basis`, `lot_count`, `gross_issued`, `allowance_bp`, `spoilage_credit`, `net_issued`, `accounted`, `gross_variance`, `net_variance`, `tolerance_bp`, `tolerance_ballots` and `ballot_accountability_status`. Its `basis` query parameter is optional and defaults to `PRELIMINARY`, the in-field view; an unrecognised basis is `ERR_INVALID_REQUEST`. Because this read is not phase-gated it can be consulted at any point during the election as a running accountability check, and it applies no completeness rule — the read under `FINAL_CANVASS` simply narrows the lot scope rather than refusing.

Finally, retention. A `WarehouseCustodian` applies the post-election retention seal to a `RETURNED` unit, supplying a `seal_number` and a `retention_days` of at least 1. This operation is not phase-gated in the ordinary way; instead it carries its own explicit gate, and the guards run in this order: the unit must resolve; its `custody_status` must be `RETURNED`, or `ERR_UNIT_STATE_INVALID`; the election's `status` must be `RECONCILED`, or `ERR_RETENTION_BEFORE_RECONCILIATION` — records are not sealed away before the count they document has been reconciled; and the seal must be unique across the election's lots and tabulators, or `ERR_SEAL_NUMBER_DUPLICATE`. On success the unit moves `RETURNED → SEALED_RETENTION`, its terminal custody state; `seal_number` is stored and `retention_until` is set to the election's `election_date` plus `retention_days` days; a custody event of type `RETENTION_SEAL` is appended; and the election's `open_seal_count` increases by one. Note that a unit returned at poll close still carries its polling-place seal, and applying the retention seal overwrites `seal_number` while incrementing the open-seal count again — the retention seal is a new seal on the record, and the ledger holds both entries in `sequence_index` order.

## 4. API Endpoint Definitions

The table below enumerates every endpoint of the service. Creation endpoints — those that bring a new resource into existence — answer `201 Created`; every other successful call answers `200 OK`, including the state-transition and side-effect endpoints, which return the mutated primary resource in `data` so a client can observe every cascaded derived field without a second read. Computed reads return their worksheet object rather than a stored entity. Path parameters are not repeated in the description; request-body fields and query parameters are specified in Section 3. In the Authorized Role(s) column, "All roles" means all seven roles of Section 2.1 — `ElectionsDirector`, `BallotCoordinator`, `LanguageAccessCoordinator`, `PrintVendorRep`, `WarehouseCustodian`, `VotingSystemTechnician` and `PublicObserver` — and the logical-clock endpoint is additionally exempt from role authorization altogether, as described in Section 2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: sets the server logical clock. No domain entity is modified. | All roles |
| POST | `/elections` | Registers an election in SETUP. | ElectionsDirector |
| GET | `/elections/{id}` | Reads one election with all derived ledger fields. | All roles |
| POST | `/elections/{id}/certify-ballot-order` | Freezes contest ordering and candidate base ordering for the election (SETUP → CONTESTS_CERTIFIED). | ElectionsDirector |
| POST | `/elections/{id}/lock-styles` | Locks every APPROVED ballot style so programming, style assignment and printing can proceed (CONTESTS_CERTIFIED → STYLES_LOCKED). | ElectionsDirector |
| POST | `/elections/{id}/deploy` | Declares pre-election deployment complete (STYLES_LOCKED → DEPLOYED). | ElectionsDirector |
| POST | `/elections/{id}/close-polls` | Closes the polls (DEPLOYED → POLLS_CLOSED) and recalls every deployed tabulator. | ElectionsDirector |
| POST | `/elections/{id}/reconcile` | Records a ballot-accountability reconciliation under the requested basis; optimistic-concurrency guarded on the election version. | ElectionsDirector |
| GET | `/elections/{id}/accountability` | Computed read: the full ballot-accountability worksheet under the requested basis, without mutating the election. | All roles |
| GET | `/elections/{id}/contests` | Lists the election contests, optionally filtered by status. | All roles |
| GET | `/elections/{id}/custody-events` | Immutable chain-of-custody ledger for the election, ordered by sequence_index ascending. | All roles |
| POST | `/elections/{id}/contests` | Files a contest against the election in DRAFT. | ElectionsDirector, BallotCoordinator |
| GET | `/contests/{id}` | Reads one contest. | All roles |
| GET | `/contests/{id}/candidates` | Lists the contest candidates ordered by base_order_index ascending then created_at ascending. | All roles |
| POST | `/contests/{id}/candidates` | Files a candidate for the contest. | ElectionsDirector, BallotCoordinator |
| POST | `/contests/{id}/certify` | Certifies the contest and every candidate filed for it (DRAFT → CERTIFIED). | ElectionsDirector |
| POST | `/contests/{id}/withdraw` | Withdraws a certified contest and cascades the withdrawal through styles, print jobs, lots, precincts and the election (depth-5 cascade). | ElectionsDirector |
| POST | `/candidates/{id}/disqualify` | Disqualifies a candidate and re-derives the printed order of the surviving siblings (depth-3 cascade). | ElectionsDirector |
| POST | `/elections/{id}/precincts` | Registers a precinct and derives its statutory ballot requirement. | ElectionsDirector, BallotCoordinator |
| GET | `/precincts/{id}` | Reads one precinct. | All roles |
| GET | `/precincts` | Lists precincts ordered by precinct_code ascending. | All roles |
| POST | `/precincts/{id}/assign-style` | Points the precinct at an APPROVED (or already LOCKED) ballot style; re-assignment is permitted while the phase allows it. | BallotCoordinator |
| POST | `/elections/{id}/ballot-styles` | Creates a ballot style in DRAFT, optionally superseding an earlier style. | BallotCoordinator |
| GET | `/ballot-styles/{id}` | Reads one ballot style. | All roles |
| GET | `/ballot-styles` | Lists ballot styles, optionally filtered. | All roles |
| GET | `/ballot-styles/{id}/layout` | Computed read: the printed layout of the style under the requested basis, contest by contest, with each candidate rotation-adjusted printed_position. basis defaults to PROVISIONAL_BASIS. | All roles |
| POST | `/ballot-styles/{id}/language-certifications` | Records the translation and alternative-format certifications for the style. Replaces both lists wholesale. | LanguageAccessCoordinator |
| POST | `/ballot-styles/{id}/request-proof` | Sends the style out for proofing (DRAFT or PROOF_REJECTED → PROOFING). | BallotCoordinator |
| POST | `/ballot-styles/{id}/proof-decision` | Approves or rejects the proof (PROOFING → APPROVED or PROOF_REJECTED). Cannot be executed by the user who requested the proof. | ElectionsDirector, BallotCoordinator |
| GET | `/ballot-styles/{id}/test-decks` | Lists the style test decks, optionally filtered by status. | All roles |
| POST | `/ballot-styles/{id}/test-decks` | Builds a logic-and-accuracy test deck for the style, validated against the style's certified layout. | VotingSystemTechnician, BallotCoordinator |
| POST | `/print-vendors` | Registers a print vendor. status defaults to ACTIVE. | ElectionsDirector |
| GET | `/print-vendors/{id}` | Reads one print vendor with its rolling defect rate. | All roles |
| POST | `/print-jobs` | Places a print order against an approved or locked style, pinning the style's version. | BallotCoordinator |
| GET | `/print-jobs/{id}` | Reads one print job with its invoice breakdown. | All roles |
| GET | `/print-jobs` | Lists print jobs, optionally filtered by election, vendor, style or status. | All roles |
| POST | `/print-jobs/{id}/approve-proof` | Approves the vendor's press proof and releases the job to print (PROOF_PENDING → PRINTING), writing the ESTIMATE invoice. | ElectionsDirector |
| POST | `/print-jobs/{id}/inspect` | Records a quality-inspection sample and re-derives the cumulative defect rate (PRINTING or QC_HOLD → QC_PASSED or QC_HOLD). | WarehouseCustodian |
| POST | `/print-jobs/{id}/deliver` | Records the vendor secure delivery: creates one ballot lot per shipped pallet and rewrites the invoice on the FINAL basis (QC_PASSED -> DELIVERED). | PrintVendorRep |
| GET | `/ballot-lots/{id}` | Reads one ballot lot with its full accounting line. | All roles |
| GET | `/ballot-lots` | Lists ballot lots ordered by lot_code ascending, then created_at ascending. | All roles |
| POST | `/ballot-lots/{id}/receive` | Receives a shipped lot into the warehouse after verifying its seal (IN_TRANSIT → RECEIVED). | WarehouseCustodian |
| POST | `/ballot-lots/{id}/issue` | Issues a received lot to a precinct (RECEIVED → ISSUED). The lot's style must be the precinct's assigned style. | WarehouseCustodian |
| POST | `/ballot-lots/{id}/recall` | Compensating action: pulls an issued lot back into the warehouse (ISSUED → RECEIVED) and reverses every side effect of the issue. | WarehouseCustodian |
| POST | `/ballot-lots/{id}/return-counts` | Records the precinct's post-election ballot accounting for the lot (ISSUED → RETURNED). | WarehouseCustodian |
| POST | `/elections/{id}/tabulator-units` | Registers a tabulator in the vault, unprogrammed. | VotingSystemTechnician |
| GET | `/tabulator-units/{id}` | Reads one tabulator with both of its state axes. | All roles |
| GET | `/tabulator-units` | Lists tabulators ordered by asset_tag ascending. | All roles |
| POST | `/tabulator-units/{id}/program` | Programs the unit for a locked ballot style (UNPROGRAMMED or LA_FAILED → PROGRAMMED). | VotingSystemTechnician |
| POST | `/tabulator-units/{id}/deploy` | Seals a tested unit and deploys it to a precinct that already holds issued ballots (IN_VAULT → DEPLOYED). | WarehouseCustodian |
| POST | `/tabulator-units/{id}/break-seal` | Compensating action: breaks the deployment seal and returns the unit to the vault (DEPLOYED → IN_VAULT), reversing the seal ledger entry. | WarehouseCustodian |
| POST | `/tabulator-units/{id}/seal-retention` | Applies the post-election retention seal to a returned unit (RETURNED → SEALED_RETENTION). Only permitted once the election is reconciled. | WarehouseCustodian |
| POST | `/la-test-sessions` | Schedules a public logic-and-accuracy test for a programmed unit against a draft deck, enforcing the unit's buffered window exclusivity. | VotingSystemTechnician |
| GET | `/la-test-sessions/{id}` | Reads one logic-and-accuracy session. | All roles |
| GET | `/la-test-sessions` | Lists logic-and-accuracy sessions, optionally filtered. | All roles |
| POST | `/la-test-sessions/{id}/observers` | Signs a public observer in to a scheduled session. | VotingSystemTechnician, PublicObserver |
| POST | `/la-test-sessions/{id}/start` | Opens the public logic-and-accuracy test (SCHEDULED → IN_PROGRESS), enforcing notice lead, observer minimum, admission window and segregation of duties. | VotingSystemTechnician |
| POST | `/la-test-sessions/{id}/record-results` | Records the tabulator's reported tallies, derives the discrepancy count and closes the session (IN_PROGRESS → PASSED or FAILED). | VotingSystemTechnician |

## 5. Error Code Reference

Every error response uses the envelope of Section 2.2, with the `error_id` drawn from the table below. When more than one condition is violated by the same request, the returned identifier is decided by the precedence order of Section 2.6, not by the order in which the fields appear in the request body.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ELECTION_NOT_FOUND` | 404 |
| `ERR_CONTEST_NOT_FOUND` | 404 |
| `ERR_CANDIDATE_NOT_FOUND` | 404 |
| `ERR_PRECINCT_NOT_FOUND` | 404 |
| `ERR_BALLOT_STYLE_NOT_FOUND` | 404 |
| `ERR_PRINT_VENDOR_NOT_FOUND` | 404 |
| `ERR_PRINT_JOB_NOT_FOUND` | 404 |
| `ERR_BALLOT_LOT_NOT_FOUND` | 404 |
| `ERR_TABULATOR_NOT_FOUND` | 404 |
| `ERR_TEST_DECK_NOT_FOUND` | 404 |
| `ERR_LA_SESSION_NOT_FOUND` | 404 |
| `ERR_STALE_ELECTION_VERSION` | 412 |
| `ERR_STALE_BALLOT_STYLE_VERSION` | 412 |
| `ERR_ELECTION_PHASE_INVALID` | 409 |
| `ERR_CONTEST_STATE_INVALID` | 409 |
| `ERR_CANDIDATE_STATE_INVALID` | 409 |
| `ERR_STYLE_STATE_INVALID` | 409 |
| `ERR_JOB_STATE_INVALID` | 409 |
| `ERR_LOT_STATE_INVALID` | 409 |
| `ERR_UNIT_STATE_INVALID` | 409 |
| `ERR_DECK_STATE_INVALID` | 409 |
| `ERR_SESSION_STATE_INVALID` | 409 |
| `ERR_VENDOR_NOT_SECURE` | 409 |
| `ERR_PROOF_VERSION_STALE` | 409 |
| `ERR_LOT_NOT_FOR_PRECINCT` | 409 |
| `ERR_UNIT_STYLE_MISMATCH` | 409 |
| `ERR_SEAL_MISMATCH` | 409 |
| `ERR_SEAL_NUMBER_DUPLICATE` | 409 |
| `ERR_PRESS_CAPACITY_EXCEEDED` | 409 |
| `ERR_UNIT_TEST_WINDOW_CONFLICT` | 409 |
| `ERR_PUBLIC_NOTICE_TOO_LATE` | 409 |
| `ERR_OUTSIDE_TEST_WINDOW` | 409 |
| `ERR_INSUFFICIENT_OBSERVERS` | 409 |
| `ERR_LANGUAGE_COVERAGE_INCOMPLETE` | 409 |
| `ERR_EMPTY_TEST_DECK` | 409 |
| `ERR_DECK_MARK_OFF_STYLE` | 409 |
| `ERR_DECK_MARKS_EXCEED_CAPACITY` | 409 |
| `ERR_NO_CERTIFIED_CONTESTS` | 409 |
| `ERR_BALLOT_ORDER_COLLISION` | 409 |
| `ERR_DEPLOYMENT_NOT_READY` | 409 |
| `ERR_LOTS_NOT_RETURNED` | 409 |
| `ERR_RETENTION_BEFORE_RECONCILIATION` | 409 |
| `ERR_QUANTITY_BELOW_REQUIREMENT` | 409 |
| `ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT` | 409 |
| `ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT` | 409 |
