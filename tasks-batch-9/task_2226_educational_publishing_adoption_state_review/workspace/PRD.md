# Adoption Review Press API — Product Requirements Document

## 1. Introduction

State textbook adoption is the single highest-stakes commercial event in kindergarten-through-twelfth-grade publishing, and it is also the least forgiving. A state opens a subject rotation slot on a calendar published years in advance, accepts submissions only inside a narrow window, demands correlation documentation that maps every page of a program to its own academic framework, seats a citizen review committee that hears each publisher in a timed slot, publishes every comment the public files against the program, and then decides — once — which editions districts may buy for the length of a multi-year contract. Miss the filing window by an hour, cite a framework code the state retired, ship one sample copy fewer than the state asked for, or leave a prohibited content tag in the edition, and the program sits out the entire cycle.

The Adoption Review Press API is the publisher's operational system of record for that process, and simultaneously the state's instrument for running it. It carries the adoption calendar as an explicit phase pipeline that only advances when the logical clock says a phase is due; it carries the catalog of print editions together with their press signature budget and their warehouse ledger; it carries the state-specific content edits that adapt a national program to one state's required topics and prohibited content; it carries the correlation evidence and the committee's verdict on each citation; it carries public comments and the response clock they start; it carries multi-year price filings with their volume, term and ancillary-bundling discounts; and it carries the district orders that finally draw against an adopted list. Every one of those artifacts is auditable, because in an adoption dispute the publisher must be able to show what it knew, when it knew it, and which revision of the edition the state actually reviewed.

Two engineering themes run through the whole specification and deserve early emphasis. The first is **pinning**: a submission freezes the edition's content revision at the moment it is filed, and any later editorial change to that edition makes the filed submission stale, cancels its committee slot, and blocks adoption until the publisher re-files. The second is **segregation of duties**: the editor who proposes a content change may not approve it, and the sales representative who enters a district order may not confirm it. Together these two themes generate most of the system's cascading behaviour, and they are the reason the API tracks versions and originating user identifiers on resources that would otherwise be simple records.

## 2. Global Specifications & System-Wide Principles

This section fixes the contracts that hold everywhere in the API: authentication, the response envelope, pagination, resource identity, the logical clock, the order in which validations fire, concurrency protection, numeric precision, and the conserved quantities the system refuses to break. Endpoint paths in this section are given literally; the business narratives in Section 3 refer to operations by what they do rather than by their URLs.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. If either header is absent, or if `X-User-Role` is not one of the eight roles named below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well formed but the declared role is not among the roles the addressed endpoint permits, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The eight roles are `PlatformAdmin`, `StateAdoptionOfficer`, `ReviewCommitteeMember`, `PublisherEditor`, `EditorialDirector`, `PricingManager`, `SalesRep` and `PublicCommenter`.

- `PlatformAdmin` operates the publishing platform. It seeds state profiles and titles, moves warehouse inventory, and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.
- `StateAdoptionOfficer` is an officer of exactly one adopting state. When `X-User-Role` is `StateAdoptionOfficer`, `X-User-ID` is the `id` of the acting `StateProfile`; ownership checks on any resource that references a `StateProfile` compare the resource's state foreign key to `X-User-ID`. Concretely, the officer's own state is compared against `AdoptionCycle.state_id` for a cycle, against the state of the cycle that owns a `CommitteePanel`, a `PresentationSlot` or a `PricingProposal`, and against the path-addressed `StateProfile` when a framework standard is added. Acting outside that state fails with `ERR_STATE_SCOPE_VIOLATION` (HTTP 403).
- `ReviewCommitteeMember` is a seated committee member who judges correlation evidence and casts ballots. When `X-User-Role` is `ReviewCommitteeMember`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server records it as `verdict_by_user_id` on a `CorrelationEntry` whose verdict the member registers and as `member_user_id` on a `CommitteeVote` the member casts, but it does not compare it to any entity's `id`.
- `PublisherEditor` is the publisher-side editor who builds submissions and correlation documentation, files with the state, ships samples, releases editions and answers public comments. When `X-User-Role` is `PublisherEditor`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server records it as `proposed_by_user_id` on a `ContentEdit` the editor proposes or resubmits, but does not compare it to any entity's `id`.
- `EditorialDirector` is the editorial approver who reviews, applies and reverts state-specific content edits, plans revision cycles and adjusts warehouse inventory. When `X-User-Role` is `EditorialDirector`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server records it as `reviewed_by_user_id` on a reviewed `ContentEdit`, but does not compare it to any entity's `id`.
- `PricingManager` is the publisher-side pricing owner who defines ancillary bundles and files multi-year price proposals. When `X-User-Role` is `PricingManager`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is not compared to any entity's `id`.
- `SalesRep` is the field sales representative who quotes, confirms, fulfils and cancels district orders. When `X-User-Role` is `SalesRep`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server records it as `created_by_user_id` on an order the rep enters and as `confirmed_by_user_id` on an order the rep confirms, but does not compare it to any entity's `id`.
- `PublicCommenter` is a member of the public filing comments against submissions. When `X-User-Role` is `PublicCommenter`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is not compared to any entity's `id`.

Two operations additionally enforce **segregation of duties** by comparing the acting `X-User-ID` against a recorded originator. Reviewing a content edit requires an `X-User-ID` different from that edit's `proposed_by_user_id`; confirming a district order requires an `X-User-ID` different from that order's `created_by_user_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). These are the only two endpoints that apply this rule.

The state-scope rule of `ERR_STATE_SCOPE_VIOLATION` guards exactly ten operations: adding a standard to a state framework (`POST /state-profiles/{id}/standards`), creating an adoption cycle (`POST /adoption-cycles`), advancing a cycle phase (`POST /adoption-cycles/{id}/phase-advance`), seating a panel (`POST /committee-panels`), reserving a slot (`POST /committee-panels/{id}/slots`), opening a session (`POST /committee-panels/{id}/open-session`), closing a session (`POST /committee-panels/{id}/close-session`), marking a submission presented (`POST /presentation-slots/{id}/present`), tallying a slot (`POST /presentation-slots/{id}/tally`), and deciding a price filing (`POST /pricing-proposals/{id}/decision`).

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

List endpoints accept two query parameters. `limit` caps the number of records returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of records to skip before the first returned record; it defaults to 0 and its minimum accepted value is 0. A `limit` outside the range from 1 to 100 inclusive, or a negative `offset`, is a request-shape failure and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, every list endpoint returns its records sorted by `created_at` in ascending order.

The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`. `total_count` is the number of records matching the request's filters before pagination is applied, and `has_more` is true when records matching the filters remain beyond the returned page.

### 2.4. Resource Identity, Timestamps and Record Versions

Every resource the API mints carries an `id`: a server-generated UUID with no type prefix and no domain-flavoured encoding. Clients never supply an `id`. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the record was first written.

Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record — and `version`, an integer that starts at 1 on creation and increments by 1 on every mutation. This includes mutations the server performs on its own initiative: when a cascade recomputes a submission's compliance counters, when a sweep cancels a presentation slot, or when a slot reservation increases a panel's `reserved_minutes`, the affected record's `updated_at` is refreshed and its `version` increments exactly as if a client had written it directly.

Two record types are append-only history rather than mutable state, and they carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from `StateStandard` and from `CommitteeVote`. A `CommitteeVote` is never edited; a member who changes position casts a fresh ballot and the earlier one is marked `superseded`.

### 2.5. The Logical Adoption Clock

Every deadline in this domain — the submission window, the phase timestamps of a cycle, a panel's session start, a slot's start, a public comment's response deadline — is evaluated against a server-held **logical UTC clock**, never against real wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server never falls back to real time under any circumstance.

A `PlatformAdmin` moves the clock by submitting `to_iso8601`, an ISO 8601 instant, to `POST /_clock/set_current_utc`; the response reports the new `current_utc`. Every phase-advance evaluation, filing-window test, session-open test, slot-start test, comment escalation test and response-deadline test performed after that call reads the new instant. This capability exists so that a multi-year adoption calendar can be exercised deterministically.

### 2.6. Validation Order and Nested Addressing

When a request targets a nested resource, the path is resolved strictly left to right and the first identifier that does not resolve determines the 404 that is returned. A verdict addressed at a correlation entry under a submission that does not exist fails with `ERR_SUBMISSION_NOT_FOUND` before the server ever looks for the entry; and an entry that exists but whose `submission_id` differs from the submission named in the path is treated as absent, yielding `ERR_CORRELATION_ENTRY_NOT_FOUND`.

More broadly, when several checks could reject one request, they are evaluated in a fixed order and the **first** failing check supplies the response. The order is:

1. Authentication — both headers present and `X-User-Role` a declared role, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. Role authorization — the acting role appears in the endpoint's permitted roles, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.
3. Request shape — required fields present, types correct, enum members recognized, numeric ranges honoured, ISO 8601 datetimes parseable, `limit` between 1 and 100 inclusive, `offset` at least 0, else `ERR_INVALID_REQUEST` (400). Applies to every endpoint.
4. A `/state-profiles` path identifier resolves to a `StateProfile`, else `ERR_STATE_PROFILE_NOT_FOUND` (404) — on reading a state profile, and on adding to or listing its standards.
5. An `/adoption-cycles` path identifier resolves to an `AdoptionCycle`, else `ERR_ADOPTION_CYCLE_NOT_FOUND` (404) — on reading a cycle, advancing its phase, and listing its panels.
6. A `/titles` path identifier resolves to a `Title`, else `ERR_TITLE_NOT_FOUND` (404) — on reading a title, releasing it, adjusting its inventory, acting on its revision plan, and creating or listing its ancillary bundles.
7. A `/content-edits` path identifier resolves to a `ContentEdit`, else `ERR_CONTENT_EDIT_NOT_FOUND` (404) — on reading, reviewing, resubmitting, applying and reverting an edit.
8. A `/submissions` path identifier resolves to a `Submission`, else `ERR_SUBMISSION_NOT_FOUND` (404) — on reading a submission and on every one of its sub-resource operations.
9. The correlation-entry identifier resolves to a `CorrelationEntry` belonging to the submission in the path, else `ERR_CORRELATION_ENTRY_NOT_FOUND` (404) — on recording an entry verdict.
10. A `/committee-panels` path identifier resolves to a `CommitteePanel`, else `ERR_COMMITTEE_PANEL_NOT_FOUND` (404) — on reading a panel, reserving a slot on it, and opening or closing its session.
11. A `/presentation-slots` path identifier resolves to a `PresentationSlot`, else `ERR_PRESENTATION_SLOT_NOT_FOUND` (404) — on reading a slot, presenting it, casting or listing its ballots, and tallying it.
12. A `/pricing-proposals` path identifier resolves to a `PricingProposal`, else `ERR_PRICING_PROPOSAL_NOT_FOUND` (404) — on reading a proposal and deciding it.
13. A `/district-orders` path identifier resolves to a `DistrictOrder`, else `ERR_DISTRICT_ORDER_NOT_FOUND` (404) — on reading, confirming, fulfilling and cancelling an order.
14. A `/public-comments` path identifier resolves to a `PublicComment`, else `ERR_PUBLIC_COMMENT_NOT_FOUND` (404) — on publishing a response to a comment.
15. Every foreign key supplied in a request body — `state_id`, `cycle_id`, `title_id`, `submission_id`, `bundle_id`, `pricing_proposal_id` — resolves to an existing record, else `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404). Applies to creating a cycle, a content edit, a submission, a panel, a slot, a pricing proposal and a district order.
16. State scope for a `StateAdoptionOfficer`, else `ERR_STATE_SCOPE_VIOLATION` (403), on the ten operations enumerated in Section 2.1.
17. `expected_submission_version` matches the submission's current `version`, else `ERR_STALE_SUBMISSION_VERSION` (412), on filing a pricing proposal.
18. `expected_panel_version` matches the panel's current `version`, else `ERR_STALE_PANEL_VERSION` (412), on reserving a presentation slot.
19. The addressed cycle's phase admits the operation, else `ERR_ADOPTION_CYCLE_STATE_INVALID` (409) — phase-advance is refused from `ARCHIVED`, and a cycle that is `DECIDED` or `ARCHIVED` admits neither panel creation, slot reservation, price filing nor submission withdrawal.
20. The addressed submission's `review_status` admits the operation, else `ERR_SUBMISSION_STATE_INVALID` (409) — adding correlations, recording entry verdicts, sampling shipments and filing all require `DRAFT`; price filing, slot reservation and comment responses all require `FILED`, `SCHEDULED` or `PRESENTED`; withdrawal requires a status the requested reason admits.
21. The addressed content edit's `status` admits the operation, else `ERR_CONTENT_EDIT_STATE_INVALID` (409) — review requires `PROPOSED`, resubmit requires `REJECTED`, apply requires `APPROVED`, revert requires `APPLIED`.
22. The addressed title's `status` admits the operation, else `ERR_TITLE_STATE_INVALID` (409) — release requires `DRAFT`; revision-plan actions require `ACTIVE` or `REVISION_PLANNED`.
23. The referenced title is not `SUNSET`, else `ERR_TITLE_SUNSET` (409), on applying a content edit, quoting a district order and confirming a district order.
24. The referenced title has been released — its `status` is `ACTIVE` or `REVISION_PLANNED` — else `ERR_TITLE_NOT_RELEASED` (409), on filing a submission and on quoting a district order.
25. The addressed panel's `status` admits the operation, else `ERR_COMMITTEE_PANEL_STATE_INVALID` (409) — slot reservation requires `SCHEDULED`, opening a session requires `SCHEDULED`, closing a session and presenting and tallying all require `IN_SESSION`, and the cycle's advance from `IN_REVIEW` to `PUBLIC_COMMENT` requires that no panel of the cycle is `IN_SESSION`.
26. The addressed slot's `status` admits the operation, else `ERR_PRESENTATION_SLOT_STATE_INVALID` (409) — presenting requires `RESERVED`, casting a ballot requires `PRESENTED`, tallying requires `PRESENTED`, and closing a session requires that no slot of the panel is `PRESENTED`.
27. The addressed price filing's `status` admits the operation, else `ERR_PRICING_PROPOSAL_STATE_INVALID` (409) — a decision requires `FILED`, and confirming an order that names a proposal requires that proposal to be `APPROVED`.
28. The addressed order's `status` admits the operation, else `ERR_DISTRICT_ORDER_STATE_INVALID` (409) — confirm requires `QUOTED`, fulfil requires `CONFIRMED`, cancel requires `QUOTED` or `CONFIRMED`; the same code also refuses a revision-plan sunset while any order of the title is `CONFIRMED`.
29. The addressed comment is `OPEN` or `ESCALATED`, else `ERR_PUBLIC_COMMENT_STATE_INVALID` (409), on publishing a response.
30. Filing requires the owning cycle to be `OPEN`, else `ERR_CYCLE_NOT_OPEN_FOR_SUBMISSION` (409).
31. The submission's `pinned_content_revision` still matches its title's `content_revision`, that is `content_pin_stale` is false, else `ERR_CONTENT_PIN_STALE` (409), on reserving a slot and on presenting.
32. Segregation of duties, else `ERR_SEGREGATION_OF_DUTIES` (403), on reviewing a content edit and confirming a district order.
33. No prohibited content tag of the state remains in the title's content, else `ERR_PROHIBITED_CONTENT_PRESENT` (422), on filing.
34. Every required topic of the state is supplied, else `ERR_REQUIRED_TOPIC_MISSING` (422), on filing.
35. When a bundle is named, its accessibility conformance meets the state's demand, else `ERR_ACCESSIBILITY_COMMITMENT_MISSING` (422), on filing a price proposal.
36. When a bundle is named and the state demands a signed privacy addendum, the bundle has one, else `ERR_PRIVACY_ADDENDUM_MISSING` (422), on filing a price proposal.
37. When a bundle is named, its rostering standard equals the state's, else `ERR_ROSTERING_STANDARD_UNSUPPORTED` (422), on filing a price proposal.
38. The cited `standard_code` exists in the framework of the cycle's state and subject, else `ERR_STANDARD_NOT_IN_FRAMEWORK` (422), on adding a correlation entry.
39. When a bundle is named, it belongs to the submission's title, else `ERR_BUNDLE_TITLE_MISMATCH` (422), on filing a price proposal.
40. In an `ADOPTION_LIST` state the order names a price filing, else `ERR_PRICING_PROPOSAL_REQUIRED` (422), on confirming an order.
41. In an `ADOPTION_LIST` state the ordered title's `adopted_state_codes` contains the district's state code, else `ERR_TITLE_NOT_ON_ADOPTED_LIST` (422), on confirming an order.
42. No adopted submission pinned the revision this edit produced, else `ERR_EDIT_REVERT_BLOCKED` (409), on reverting an applied edit.
43. The revision target year does not collide with a live submission of the title, else `ERR_REVISION_CONFLICTS_WITH_OPEN_ADOPTION` (409), on planning a revision.
44. The logical clock sits inside the cycle's submission window, else `ERR_SUBMISSION_WINDOW_CLOSED` (422), on filing.
45. The new cycle's submission window does not intersect an existing window for the same state and subject, else `ERR_CYCLE_WINDOW_OVERLAP` (409), on creating a cycle.
46. The requested slot window lies inside the panel's session window, else `ERR_SLOT_OUTSIDE_SESSION` (422), on reserving a slot.
47. The requested slot window respects the panel's turnover buffer against every occupying slot, else `ERR_SLOT_BUFFER_CONFLICT` (409), on reserving a slot.
48. The logical clock has reached the timestamp of the phase being entered, else `ERR_PHASE_NOT_DUE` (409), on advancing a phase.
49. The logical clock has reached the panel's `session_start_at`, else `ERR_PANEL_SESSION_NOT_DUE` (409), on opening a session.
50. The logical clock has reached the slot's `start_at`, else `ERR_SLOT_NOT_STARTED` (409), on presenting.
51. The submission has at least one correlation entry, else `ERR_CORRELATION_SET_EMPTY` (422), on filing.
52. Every focus standard in the coverage input set is cited deeply enough, else `ERR_FOCUS_STANDARD_UNCOVERED` (422), on filing.
53. Self-reported coverage reaches the state's minimum, else `ERR_COVERAGE_BELOW_MINIMUM` (422), on filing.
54. The state's sampling requirement is satisfied, else `ERR_SAMPLING_INCOMPLETE` (422), on filing.
55. No other live submission exists for the same cycle and title, else `ERR_DUPLICATE_SUBMISSION` (409), on creating a submission.
56. Uniqueness of `standard_code` within a state and subject, of `bundle_code` within a title, and of `state_code` and `isbn_base` globally, else `ERR_DUPLICATE_RESOURCE` (409), on creating a state profile, a standard, a title and an ancillary bundle.
57. The rejected edit still has a review round left, else `ERR_EDIT_REVISION_LIMIT_REACHED` (409), on resubmitting.
58. The committed term does not exceed the state's or the cycle's maximum, else `ERR_TERM_YEARS_EXCEED_STATE_MAX` (422), on filing a price proposal.
59. No contract-locked price filing would be superseded, else `ERR_CONTRACT_LOCKED` (409), on filing a price proposal.
60. Counted ballots reach the panel's quorum, else `ERR_QUORUM_NOT_MET` (409), on tallying.
61. At least one counted ballot is not an abstention, else `ERR_NO_COUNTABLE_VOTES` (422), on tallying.
62. The panel's presentation-minute budget accommodates the new slot, else `ERR_PANEL_CAPACITY_EXCEEDED` (409), on reserving a slot.
63. The title carries at least one content tag, else `ERR_TITLE_NOT_RELEASABLE` (422), on releasing.
64. The computed net state price respects the state's cap, else `ERR_PRICE_CAP_EXCEEDED` (422), on filing a price proposal.
65. The resulting page count stays inside the signature budget, else `ERR_PAGE_BUDGET_EXCEEDED` (409), on applying a content edit and on releasing a title.
66. On-hand print units cover the requested units, else `ERR_INSUFFICIENT_PRINT_INVENTORY` (409), on a sampling shipment, on confirming an order and on a write-off inventory adjustment.

### 2.7. Cascading Consistency Across the Adoption Record

The adoption record is one connected graph, and the API is responsible for keeping it internally consistent without asking clients to issue follow-up requests. A single write frequently mutates several records: applying a content edit changes an edition, which invalidates filed submissions of that edition, which frees committee minutes on the panels that had seated those submissions, which in turn walks those submissions back one review step. The specification calls these chains **hops**, and each hop is caused by the hop before it, not by the original request. Every record touched by a hop has its `updated_at` refreshed and its `version` incremented, because from the record's point of view it has been modified.

Advancing a cycle's phase runs a further chain, the **shared epoch sweep**, described in full in Section 3.1. Both the revision cascade and the epoch sweep are specified as ordered steps; the order matters, because a submission's compliance recomputation must observe the comment escalations that the same run produced, and a slot cancellation must observe the compliance recomputation that preceded it.

Nothing in the system is ever recomputed lazily at read time. Counters such as `submission_count`, `scheduled_submission_count`, `adopted_count`, `reserved_minutes`, `compliance_score`, `self_reported_coverage_pct` and `verified_coverage_pct` are maintained eagerly by the writes that affect them, and a read simply reports the stored value.

### 2.8. Stale-Version Protection on Submissions and Panels

Two write operations require the client to prove it is acting on a view of a parent record that is still current. Both use the parent's `version` field described in Section 2.4.

Filing a pricing proposal (`POST /pricing-proposals`) requires `expected_submission_version` as a non-optional field of the request body, carrying the client's last observed `version` of the `Submission` named by `submission_id`. If that value does not equal the submission's current `version`, the request is rejected with `ERR_STALE_SUBMISSION_VERSION` (HTTP 412). This exists because a price filing supersedes any live filing on the same submission: if another filing has already been accepted and legitimately superseded the proposal the client believed was live, then the client's view of which proposal is current is stale, and letting the write through would silently discard a filing the client never saw. Every accepted filing increments the submission's `version` by 1, so a client must re-read the submission before filing again.

Reserving a presentation slot (`POST /committee-panels/{id}/slots`) requires `expected_panel_version` as a non-optional field of the request body, carrying the client's last observed `version` of the addressed `CommitteePanel`. If that value does not equal the panel's current `version`, the request is rejected with `ERR_STALE_PANEL_VERSION` (HTTP 412). This exists because each reservation consumes part of the panel's minute budget: if another reservation has already been accepted, the client's view of the remaining session capacity is stale even when the specific window it asked for is still free. Every accepted reservation increments the panel's `version` by 1.

No other endpoint accepts a version field, and no other endpoint performs a stale-version check.

### 2.9. Numeric Precision, Rounding and Percentage Conventions

Money is carried exclusively in whole cents as integers; there are no fractional-cent amounts anywhere in the API. Wherever a monetary result is produced from a multiplication, the result is rounded to a whole number of cents using the round-half-up method, in which a value exactly halfway between two integers rounds away from zero.

Percentages come in two shapes and they must not be confused. Coverage percentages — `self_reported_coverage_pct` and `verified_coverage_pct` — are expressed on a 0-to-100 scale, carried at 2 decimal places with round-half-up, and capped at 100.00. Discount percentages — `volume_discount_pct`, `term_discount_pct`, `bundle_discount_pct` and `total_discount_pct` — are expressed as fractions of one, carried at 2 decimal places, so a twelve-percent volume discount is stored as 0.12. A correlation entry's `effective_weight` is carried at 2 decimal places with round-half-up. A slot's `recommend_ratio` is a fraction of one carried at 4 decimal places with round-half-up. `compliance_score` is an integer.

Where a formula prescribes an order of operations — round each contract year before summing the years, or decide a freight waiver on a pre-freight subtotal — that order is part of the contract, not an implementation detail, and reordering it produces results that differ by observable amounts.

### 2.10. Conserved Quantities: The Print-Unit Ledger and the Signature Page Budget

Two invariants must hold after every single write the system accepts, and any operation that would break them is refused rather than partially applied.

The **print-unit ledger** of a title states that `total_received_units` always equals the sum of `on_hand_units`, `committed_units`, `sample_reserved_units`, `fulfilled_units` and `written_off_units`. Units move between those buckets — from on-hand to committed at order confirmation, from committed to fulfilled at shipment, from on-hand to sample-reserved at a sampling shipment, from on-hand to written-off at a write-off or a sunset — but the total received never changes except when units are received. Whenever a movement would drive `on_hand_units` below zero, the operation is refused with `ERR_INSUFFICIENT_PRINT_INVENTORY`.

The **signature page budget** of a title states that `page_count` plus `page_budget_remaining` always equals `signature_page_capacity`, the immutable press signature capacity fixed when the edition was created. Applying a content edit moves pages between the two halves of that identity; reverting the edit moves them back. Any apply that would drive `page_count` above `signature_page_capacity` or below 1 is refused with `ERR_PAGE_BUDGET_EXCEEDED`.

### 2.11. Digital Platform Commitments: Accessibility, Rostering and Data Privacy

States do not buy print alone; they buy a digital platform with it, and they gate the purchase on three commitments the publisher must make in advance. Each `StateProfile` declares an `accessibility_standard` — either `WCAG_2_1_AA` or `WCAG_2_2_AA`, defaulting to `WCAG_2_1_AA` — a `rostering_standard` chosen from `ONEROSTER_1_1`, `ONEROSTER_1_2` and `CSV_MANUAL`, defaulting to `ONEROSTER_1_2`, and a boolean `data_privacy_addendum_required` that defaults to true.

Each `AncillaryBundle` carries the matching commitments: an `accessibility_conformance` chosen from `WCAG_2_1_AA`, `WCAG_2_2_AA` and `NONE`, its own `rostering_standard` chosen from `ONEROSTER_1_1`, `ONEROSTER_1_2` and `CSV_MANUAL`, and a boolean `privacy_addendum_signed` that defaults to false.

The three commitments are compared at the moment a price is filed with the state, and only when the filing actually names a bundle. Accessibility is a **ranked** comparison in which `WCAG_2_2_AA` is stronger than `WCAG_2_1_AA`: a bundle conforming to `WCAG_2_2_AA` satisfies a state demanding either level, a bundle conforming to `WCAG_2_1_AA` satisfies only a state demanding `WCAG_2_1_AA`, and a bundle conforming to `NONE` satisfies no state at all. Rostering, by contrast, is an **exact** comparison: the bundle's `rostering_standard` must equal the state's, and a stronger-looking standard does not substitute for the one the state's systems actually speak. Privacy is a simple conjunction: when the state's `data_privacy_addendum_required` is true, the bundle's `privacy_addendum_signed` must be true. The three rejections are `ERR_ACCESSIBILITY_COMMITMENT_MISSING`, `ERR_ROSTERING_STANDARD_UNSUPPORTED` and `ERR_PRIVACY_ADDENDUM_MISSING`, and per Section 2.6 accessibility is tested first, then privacy, then rostering.

## 3. Business Logic & Workflows

### 3.1. States, Academic Frameworks and the Adoption Calendar

Everything begins with a state. A `PlatformAdmin` registers an adopting state by supplying its `state_code` — exactly two uppercase letters, unique across the whole platform — and its `adoption_model`, which is either `ADOPTION_LIST` for a state that publishes an adopted list districts must buy from, or `OPEN_TERRITORY` for a state whose districts buy directly. The rest of the profile describes what the state demands of publishers, and each field has a default that applies when the field is omitted. `sampling_copies_required` is the number of print sample copies that must reach the state before a submission may be filed; it defaults to 0 and must be between 0 and 50 inclusive. `comment_response_days` is the number of calendar days the publisher has to answer a public comment before it escalates; it defaults to 10 and must be between 1 and 60 inclusive. `required_topics` and `prohibited_content_tags` are arrays of uppercase snake_case codes, each defaulting to empty and each capped at 20 entries — the first names topics that must be present in submitted content, the second names tags the state forbids in adopted instructional materials. `multi_year_max_years` caps the contract term a price filing may commit to; it defaults to 6 and must be between 1 and 10 inclusive. `price_cap_cents` is the maximum net state price the state accepts per copy across a whole term; it defaults to null, meaning uncapped, and when supplied must be at least 1. `min_verified_coverage_pct` is the minimum correlation coverage percentage; it defaults to 85.00, must lie between 0.00 and 100.00, and is carried at two decimals. A duplicate `state_code` is refused with `ERR_DUPLICATE_RESOURCE`. Registering a state profile is the exclusive privilege of `PlatformAdmin`; the accessibility, rostering and privacy fields of the profile are described in Section 2.11.

A state's academic framework is built one standard at a time, by a `PlatformAdmin` or by the `StateAdoptionOfficer` of that very state. Each `StateStandard` belongs to the state addressed in the path — its `state_id` is taken from the path and never from the body — and declares the `subject` rotation slot it sits in, one of `MATH`, `ELA`, `SCIENCE` and `SOCIAL_STUDIES`; a `standard_code` of 1 to 40 characters that correlation entries will cite, unique within the pair of state and subject; a grade band given as `grade_low` and `grade_high`, where kindergarten is grade 0, both values lie between 0 and 12 inclusive, and `grade_low` is at most `grade_high`; a `weight` between 1 and 5 inclusive that determines how much of the coverage denominator this standard occupies; and a boolean `is_focus` that defaults to false. Focus standards receive special treatment at filing time, as Section 3.5 explains. The framework can be listed back, optionally narrowed by `subject` and by `is_focus`, with `limit` and `offset` paging the result.

An `AdoptionCycle` is the state's calendar entry for one subject rotation slot, and only a `StateAdoptionOfficer` may open one — for its own state, since `state_id` in the body must equal the acting `X-User-ID`. The cycle names its `subject` and its `cycle_year`, an adoption year label between 2020 and 2100 inclusive, together with six phase timestamps that must be supplied in non-decreasing order with two strict steps: `submission_deadline_at` must be strictly after `submission_open_at`; `committee_review_at` must be at or after `submission_deadline_at`; `public_comment_start_at` must be at or after `committee_review_at`; `public_comment_end_at` must be strictly after `public_comment_start_at`; and `adoption_decision_at` must be at or after `public_comment_end_at`. A `contract_term_years` between 1 and 10 inclusive caps the term any price filing in this cycle may commit to. New cycles are born `SCHEDULED` with `phase_epoch` at 0 and every submission counter at 0.

Because a state cannot run two overlapping submission windows for the same subject, the window `submission_open_at` through `submission_deadline_at` is treated as **half-open**: it includes its opening instant and excludes its closing instant. A new cycle is refused with `ERR_CYCLE_WINDOW_OVERLAP` when its window intersects the window of any existing cycle sharing the same state and the same `subject`. Two windows that merely touch at an endpoint — one closing exactly when the next opens — do not intersect and are accepted.

The calendar advances by explicit **phase-advance runs**, each performed by the cycle's own `StateAdoptionOfficer`. A single run advances the cycle at most **one** step along `SCHEDULED → OPEN → CLOSED_FOR_SUBMISSION → IN_REVIEW → PUBLIC_COMMENT → DECIDED → ARCHIVED`, and only when the logical clock has reached the timestamp belonging to the phase being entered: `submission_open_at` to enter `OPEN`, `submission_deadline_at` to enter `CLOSED_FOR_SUBMISSION`, `committee_review_at` to enter `IN_REVIEW`, `public_comment_start_at` to enter `PUBLIC_COMMENT`, `adoption_decision_at` to enter `DECIDED`, and `adoption_decision_at` plus an archive delay of 30 calendar days to enter `ARCHIVED`. Each of those tests is inclusive — the clock standing exactly on the timestamp is sufficient. A run whose clock test fails changes nothing and is rejected with `ERR_PHASE_NOT_DUE`. Once the cycle reaches `ARCHIVED` it is read-only and every further run is rejected with `ERR_ADOPTION_CYCLE_STATE_INVALID`. Every successful run increments `phase_epoch` by 1, so the counter records how many advances the cycle has actually taken.

Every successful run also executes the **shared epoch sweep**, in this fixed three-step order. Step one: each public comment on a submission of this cycle whose `status` is `OPEN` and whose `response_due_at` is at or before the current logical clock moves to `ESCALATED`, with `was_overdue_at_response` set to true. Step two: each submission of this cycle recomputes `unresolved_critical_count`, `overdue_response_count`, `compliance_score` and `adoption_blocked`. Step three: for each submission that is now blocked from adoption, every one of its presentation slots whose `status` is `RESERVED` moves to `CANCELLED` and that slot's panel has its `reserved_minutes` reduced by the slot's `duration_minutes`; then, if the submission keeps no slot in `RESERVED`, `PRESENTED` or `TALLIED`, its `review_status` steps back from `SCHEDULED` to `FILED` and its cycle's `scheduled_submission_count` decreases by 1. The ordering is load-bearing: step two must see the escalations step one produced, and step three must see the blocking decision step two produced.

Three of the six advances carry additional consequences beyond the sweep. Entering `CLOSED_FOR_SUBMISSION` from `OPEN` moves every submission of the cycle whose `review_status` is still `DRAFT` to `WITHDRAWN` — the window has closed and an unfiled draft can never be filed. Entering `IN_REVIEW` from `CLOSED_FOR_SUBMISSION` makes the cycle's panels eligible to open their sessions. Entering `PUBLIC_COMMENT` from `IN_REVIEW` is refused with `ERR_COMMITTEE_PANEL_STATE_INVALID` while any panel of the cycle is still `IN_SESSION`, because the state cannot move to public comment with a hearing still open. Entering `DECIDED` from `PUBLIC_COMMENT` runs the sweep **first** and then closes the cycle out: every submission still in `FILED`, `SCHEDULED` or `PRESENTED` moves to `NOT_ADOPTED`; each such submission's slots that are still `RESERVED` move to `CANCELLED` with their panels' `reserved_minutes` reduced by the respective `duration_minutes`; and `submission_count` and `scheduled_submission_count` are both recomputed to 0. Entering `ARCHIVED` from `DECIDED` adds nothing beyond the epoch increment and the read-only lock.

The three counters on a cycle have precise definitions. `submission_count` is the number of the cycle's submissions whose `review_status` is `FILED`, `SCHEDULED` or `PRESENTED`. `scheduled_submission_count` is the number whose `review_status` is exactly `SCHEDULED`. `adopted_count` is the number whose `review_status` is `ADOPTED` or `ADOPTED_WITH_CONDITIONS`. Cycles can be listed and filtered by `state_id`, `subject`, `cycle_year` and `status`, and a cycle's seated panels can be listed and filtered by panel `status`.

### 3.2. The Catalog: Print Editions, Ancillary Bundles and Warehouse Inventory

A `Title` is one print program edition. A `PlatformAdmin` or a `PublisherEditor` creates it with an `isbn_base` of exactly 13 characters, unique across the platform, a `subject` from the same four-member set the frameworks use, a grade band of `grade_low` and `grade_high` obeying the same 0-to-12 rules as a standard, a `copyright_year` between 2015 and 2100 inclusive, an `edition_number` that defaults to 1 and must be at least 1, a `page_count` of at least 1, a `signature_page_capacity` that must be at least the creation `page_count`, a `list_price_cents` of at least 1, and an optional array of `content_tags` — uppercase snake_case tags, at most 40 of them — describing the topics and content actually present in the edition. On creation, `page_budget_remaining` is set to `signature_page_capacity` minus `page_count`, `content_revision` is set to 1, every inventory counter is set to 0, and `status` is `DRAFT`. A duplicate `isbn_base` is refused with `ERR_DUPLICATE_RESOURCE`.

After creation, `content_tags` and `page_count` are no longer client-writable: they change only through the content-edit apply and revert operations of Section 3.3. This is deliberate — the state review file must be able to reconstruct exactly which editorial decision changed the edition and why.

A `PublisherEditor` releases a `DRAFT` edition, moving `status` from `DRAFT` to `ACTIVE` and optionally recording a `note` for the catalog record. Release is refused with `ERR_TITLE_NOT_RELEASABLE` when `content_tags` is empty, since an edition with no declared content cannot be correlated to any framework, and refused with `ERR_PAGE_BUDGET_EXCEEDED` when `page_count` exceeds `signature_page_capacity`. Only after release may the edition be submitted to a state, priced, or ordered by a district.

Revision planning is the `EditorialDirector`'s job and is driven by an `action` field taking one of three values. `PLAN` moves the edition from `ACTIVE` to `REVISION_PLANNED` and records `revision_target_cycle_year`, the adoption year the next edition is being planned against; the field is required for this action and its absence is an `ERR_INVALID_REQUEST`. Because a publisher must not plan a replacement edition into a year where the current edition is still competing, `PLAN` is refused with `ERR_REVISION_CONFLICTS_WITH_OPEN_ADOPTION` when any submission of this title has a `review_status` of `FILED`, `SCHEDULED` or `PRESENTED` inside a cycle whose `cycle_year` is at or after the requested `revision_target_cycle_year`. `CANCEL_PLAN` moves the edition from `REVISION_PLANNED` back to `ACTIVE` and resets `revision_target_cycle_year` to null; the cycle `ACTIVE → REVISION_PLANNED → ACTIVE` may be walked any number of times. `SUNSET` moves the edition from `REVISION_PLANNED` to `SUNSET`, the terminal catalog state, and is refused with `ERR_DISTRICT_ORDER_STATE_INVALID` while any district order of the title is `CONFIRMED` — the publisher cannot retire an edition it has promised to ship. A successful sunset writes off the whole remaining shelf: `written_off_units` increases by the current `on_hand_units` and `on_hand_units` becomes 0, which leaves the print-unit ledger identity of Section 2.10 intact. After sunset, further district orders and further content-edit applies on the edition are refused with `ERR_TITLE_SUNSET`. Both `CANCEL_PLAN` and `SUNSET` require the edition to be `REVISION_PLANNED` and fail with `ERR_TITLE_STATE_INVALID` otherwise.

Warehouse movement is performed by a `PlatformAdmin` or an `EditorialDirector` through inventory adjustments, each carrying an `adjustment_type`, a whole number of `units` and an optional `reason`. An `adjustment_type` of `RECEIPT` adds the units to both `total_received_units` and `on_hand_units`; an `adjustment_type` of `WRITE_OFF` subtracts them from `on_hand_units` and adds them to `written_off_units`, and is refused with `ERR_INSUFFICIENT_PRINT_INVENTORY` when `on_hand_units` is below the requested `units`. The remaining counters — `committed_units`, `sample_reserved_units` and `fulfilled_units` — move only through the sampling and district-order flows of Sections 3.4 and 3.9. The `adopted_state_codes` array records the `state_code` of every state where a submission of this edition reached an adopted status, and it is written only by the committee tally of Section 3.8.

Ancillary bundles are the `PricingManager`'s instrument for wrapping a core program with its supporting components and its digital platform. A bundle is created under the edition it wraps, so its `title_id` comes from the path, and it declares a `bundle_code` of 1 to 30 characters unique within that edition, a `component_count` between 1 and 12 inclusive, a `component_list_total_cents` of at least 1 summing the components' list prices, and a `digital_seat_price_cents` of at least 1 giving the list price per digital student seat. The `component_count` is what drives the ancillary bundling discount described in Section 3.6, and the platform commitments the bundle makes are the subject of Section 2.11. A duplicate `bundle_code` within the same edition is refused with `ERR_DUPLICATE_RESOURCE`. Bundles of an edition can be listed and filtered by `rostering_standard`.

### 3.3. State-Specific Content Editing and the Revision Cascade

A national program rarely satisfies a state verbatim, and the `ContentEdit` is how the publisher records each adaptation for the state review file. A `PublisherEditor` proposes an edit naming the `title_id` of the edition being changed and the `state_id` of the state whose requirement motivates the change, an `edit_type` from `ADD_REQUIRED_TOPIC`, `REMOVE_PROHIBITED_TAG` and `REGIONAL_SUBSTITUTION`, a `topic_code` in uppercase snake_case of 1 to 40 characters naming the topic added or the prohibited tag removed, a signed `pages_delta` between -80 and 80 inclusive giving the change in page count the edit will cause, and a `rationale` of 10 to 500 characters justifying the change editorially. The new edit is `PROPOSED` with `revision_round` at 1, `proposed_by_user_id` taken from the acting `X-User-ID`, `reviewed_by_user_id` null and `rejection_reason` null. Edits can be listed and filtered by `title_id`, `state_id`, `edit_type` and `status`.

Review is the `EditorialDirector`'s decision and carries a `verdict` field. A `verdict` of `APPROVE` moves the edit from `PROPOSED` to `APPROVED`, records `reviewed_by_user_id` and clears `rejection_reason` back to null. A `verdict` of `REJECT` moves the edit from `PROPOSED` to `REJECTED`, records `reviewed_by_user_id`, and stores the `rejection_reason` supplied in the body; a `REJECT` verdict with no `rejection_reason` is an `ERR_INVALID_REQUEST`. Both verdicts require an acting `X-User-ID` different from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`.

A rejected edit can be reworked. The `PublisherEditor` resubmits it, moving it from `REJECTED` back to `PROPOSED`, incrementing `revision_round` by 1, overwriting `proposed_by_user_id` with the resubmitting `X-User-ID`, and overwriting the stored `topic_code`, `pages_delta` and `rationale` with whichever of those three the resubmission supplies. The loop `PROPOSED → REJECTED → PROPOSED` is bounded: resubmission is permitted only while `revision_round` is strictly less than 3, so an edit that has already been proposed three times cannot go round again and the attempt is refused with `ERR_EDIT_REVISION_LIMIT_REACHED`.

Applying an approved edit is where the cascade lives, and it is the `EditorialDirector` who triggers it. Two preconditions guard the apply beyond the edit's own status. The edition must not be `SUNSET`, else `ERR_TITLE_SUNSET`; and the resulting page count — the edition's current `page_count` plus the edit's `pages_delta` — must be at most `signature_page_capacity` and at least 1, else `ERR_PAGE_BUDGET_EXCEEDED` in either direction.

The apply then runs four hops, each caused by the one before it.

**Hop one** rewrites the edition. `page_count` increases by `pages_delta` and `page_budget_remaining` decreases by the same `pages_delta`, so the signature identity of Section 2.10 still holds; `content_revision` increases by 1; and `content_tags` changes according to `edit_type` — for `ADD_REQUIRED_TOPIC` the `topic_code` is added to `content_tags`, for `REMOVE_PROHIBITED_TAG` the `topic_code` is removed from `content_tags`, and for `REGIONAL_SUBSTITUTION` `content_tags` is left exactly as it was. The edit's `status` becomes `APPLIED`.

**Hop two** is caused by hop one's `content_revision` bump. Every submission whose `title_id` is this edition, whose `review_status` is `FILED`, `SCHEDULED` or `PRESENTED`, and whose `pinned_content_revision` is strictly less than the edition's new `content_revision`, sets `content_pin_stale` to true, recomputes `prohibited_hit_count`, `missing_required_topic_count` and `compliance_score`, and sets `adoption_blocked` to true. The state reviewed one revision of the edition; it has not reviewed this one.

**Hop three** is caused by hop two's staleness flag. Every presentation slot of those newly stale submissions whose `status` is `RESERVED` moves to `CANCELLED`, and each such slot's panel has `reserved_minutes` reduced by that slot's `duration_minutes`, returning the minutes to the panel's budget.

**Hop four** is caused by hop three's cancellations. Each affected submission that now keeps no slot in `RESERVED`, `PRESENTED` or `TALLIED` moves its `review_status` from `SCHEDULED` back to `FILED`, and its cycle's `scheduled_submission_count` decreases by 1.

Reverting an applied edit is the compensating arc, again performed by the `EditorialDirector`, and it may optionally record a `reason`. A revert is refused with `ERR_EDIT_REVERT_BLOCKED` when any submission of this edition has a `review_status` of `ADOPTED` or `ADOPTED_WITH_CONDITIONS` and a `pinned_content_revision` at or above the revision that this edit's apply produced: once a state has adopted a revision, the publisher may not retroactively unmake it. An accepted revert moves the edit from `APPLIED` to `REVERTED`, its terminal state, decreases `page_count` by `pages_delta` and increases `page_budget_remaining` by `pages_delta`, restoring the signature identity, and undoes the `content_tags` change the apply made. Crucially, the revert **also** increases `content_revision` by 1 rather than restoring the previous number: revision numbers are strictly monotonic, so a revert never un-stales a submission that pinned a revision before the apply. Finally, every submission of this edition in `FILED`, `SCHEDULED` or `PRESENTED` recomputes `prohibited_hit_count`, `missing_required_topic_count`, `compliance_score` and `adoption_blocked` against the restored content.

### 3.4. Building a Submission: Correlation Evidence and Sampling

A `PublisherEditor` starts a submission by naming a `cycle_id` and a `title_id`. The new record is born with `review_status` `DRAFT` and `pricing_status` `UNPRICED` — the two dimensions of the submission lifecycle advance independently of each other, and neither gates the other's transitions. Creation also seeds `sampling_status` from the state's sampling requirement and computes the compliance counters and `compliance_score` from the state's content rules, so an editor can see at a glance what still stands between the draft and a filing. Only one submission may be live for a given pair of `cycle_id` and `title_id` at a time; a second attempt is refused with `ERR_DUPLICATE_SUBMISSION` unless every existing submission for that pair has a `review_status` of `WITHDRAWN` or `NOT_ADOPTED`. Submissions can be listed and filtered by `cycle_id`, `title_id`, `review_status`, `pricing_status` and `adoption_blocked`.

**Correlation documentation** is the heart of the submission: it maps the submitted content to the state's academic framework and offers evidence for each claim. While the submission is `DRAFT`, its `PublisherEditor` adds correlation entries one at a time, each naming a `standard_code` of 1 to 40 characters, a `depth_level` of `MENTION`, `PRACTICE` or `MASTERY` claiming how deeply the content treats the standard, a `page_reference` of 1 to 40 characters locating the treatment in the edition, and an `evidence_citation` of at least 20 and at most 500 characters quoting the material verbatim. The entry's `submission_id` is taken from the path and its `reviewer_verdict` starts at `PENDING`. The cited `standard_code` must exist in the framework of the cycle's state and subject, else `ERR_STANDARD_NOT_IN_FRAMEWORK`. Each entry also stores an `effective_weight`, the cited standard's `weight` multiplied by the depth multiplier of the claimed `depth_level`, rounded half up to 2 decimal places. Entries can be listed and filtered by `reviewer_verdict` and `depth_level`.

Committee scrutiny of the evidence is the `ReviewCommitteeMember`'s work, and it is registered one entry at a time through a `verdict` field. A `verdict` of `ACCEPT` sets the entry's `reviewer_verdict` to `ACCEPTED`; a `verdict` of `INSUFFICIENT` sets it to `INSUFFICIENT`. Either way, `verdict_by_user_id` records the acting `X-User-ID`.

**Coverage** is computed from those entries whenever an entry is added, whenever an entry receives a verdict, at filing time, whenever a content edit is applied or reverted, and in step two of the epoch sweep. The computation starts from the **denominator set**: every `StateStandard` whose `state_id` equals the cycle's state and whose `subject` equals the cycle's subject, and whose grade band overlaps the edition's — meaning the standard's `grade_high` is at least the edition's `grade_low` and the standard's `grade_low` is at most the edition's `grade_high`. The denominator is the sum of `weight` over that set. If the denominator is zero — the framework declares no standard whose grade band touches the edition's — then both `self_reported_coverage_pct` and `verified_coverage_pct` are 0.00 and no further work is done.

Otherwise the numerator is built one standard at a time. For a given standard, the candidate entries are those correlation entries of this submission whose `standard_code` equals that standard's `standard_code` and whose `reviewer_verdict` is a member of the variant's accepted verdict set. If there are no candidates, the standard contributes nothing. If there are candidates, exactly one of them is chosen — the one with the highest depth multiplier, and among candidates tied on that multiplier the one with the earliest `created_at`, never the one with any particular `id` — and the standard contributes its own `weight` multiplied by that chosen entry's depth multiplier. The depth multipliers are 0.40 for `MENTION`, 0.70 for `PRACTICE` and 1.00 for `MASTERY`. The coverage percentage is then 100 multiplied by the numerator, divided by the denominator, rounded half up to 2 decimal places, and finally capped at 100.00. Correlation entries citing a framework code that is outside the grade-band overlap are stored and returned by the API but contribute nothing to either percentage, because their standard is not in the denominator set.

Two variants of that computation are stored side by side on the submission, and they differ only in which verdicts count. The **self-reported** variant accepts entries whose `reviewer_verdict` is `PENDING` or `ACCEPTED` — the publisher's own claim, which counts evidence the committee has not yet looked at — and is stored in `self_reported_coverage_pct`; it is the gate at filing time. The **committee-verified** variant accepts only entries whose `reviewer_verdict` is `ACCEPTED`, discarding both `PENDING` and `INSUFFICIENT` evidence, and is stored in `verified_coverage_pct`; it is the gate at adoption time. Because the verified variant admits a subset of the rows the self-reported variant admits, `verified_coverage_pct` is always less than or equal to `self_reported_coverage_pct` for the same data.

**Sampling** is the second obligation the publisher must discharge before filing. While the submission is `DRAFT`, its `PublisherEditor` ships print sample copies toward the state's requirement, declaring a whole number of `units` and optionally a `carrier_ref` for the shipment record. Each accepted shipment adds its `units` to the submission's cumulative `sample_copies_shipped`, and simultaneously draws the copies out of the warehouse: the edition's `on_hand_units` decreases by `units` and its `sample_reserved_units` increases by the same `units`. A shipment asking for more copies than `on_hand_units` holds is refused with `ERR_INSUFFICIENT_PRINT_INVENTORY`. After each shipment, `sampling_status` is recomputed against the state's `sampling_copies_required`: it is `NOT_REQUIRED` when the state requires zero copies; otherwise it is `SHIPPED` once `sample_copies_shipped` has reached the required number or gone beyond it, `PARTIAL` when at least one copy has shipped but the requirement is not yet met, and `PENDING` when nothing has shipped. Shipments never roll over between submissions; each submission's requirement is discharged by its own shipments only.

### 3.5. Filing With the State, and Backing Out Again

Filing is the moment the publisher commits, and it is guarded by nine conditions that a `PublisherEditor` must satisfy simultaneously. The cycle must be `OPEN`, else `ERR_CYCLE_NOT_OPEN_FOR_SUBMISSION`. The logical clock must sit inside the cycle's half-open submission window — at or after `submission_open_at` and strictly before `submission_deadline_at` — else `ERR_SUBMISSION_WINDOW_CLOSED`. The edition must have been released, meaning its `status` is `ACTIVE` or `REVISION_PLANNED`, else `ERR_TITLE_NOT_RELEASED`. At least one correlation entry must exist, else `ERR_CORRELATION_SET_EMPTY`. The submission's `prohibited_hit_count` must be zero, else `ERR_PROHIBITED_CONTENT_PRESENT`. Its `missing_required_topic_count` must be zero, else `ERR_REQUIRED_TOPIC_MISSING`. Every standard in the coverage denominator set whose `is_focus` is true must be cited by at least one correlation entry whose `depth_level` is `PRACTICE` or `MASTERY` and whose `reviewer_verdict` is `PENDING` or `ACCEPTED`, else `ERR_FOCUS_STANDARD_UNCOVERED` — a state's focus standards cannot be discharged by a passing mention. The submission's `self_reported_coverage_pct` must be at least the state's `min_verified_coverage_pct`, else `ERR_COVERAGE_BELOW_MINIMUM`. And `sampling_status` must be either `NOT_REQUIRED` or `SHIPPED`, else `ERR_SAMPLING_INCOMPLETE`; a `PARTIAL` shipment record is not enough.

A successful filing moves `review_status` from `DRAFT` to `FILED` and performs the **content pin**: `pinned_content_revision` is set to the edition's current `content_revision` and `content_pin_stale` is set to false, capturing exactly which revision of the edition the state is being asked to review. `filed_at` records the logical clock instant of the filing. The cycle's `submission_count` increases by 1, and `compliance_score` and `adoption_blocked` are recomputed.

Backing out is driven by a `reason` field with two values. A `reason` of `REVISE` walks a filed submission back to `DRAFT` so the publisher can rework it: the cycle's `submission_count` decreases by 1, `pinned_content_revision` is reset to null and `content_pin_stale` is reset to false. When the submission being revised had already reached `SCHEDULED`, the walk-back first cancels its `RESERVED` slots — moving each to `CANCELLED` and returning its `duration_minutes` to its panel's `reserved_minutes` — before the `review_status` lands on `DRAFT`. Withdrawal with `REVISE` requires the cycle to be `OPEN`, `CLOSED_FOR_SUBMISSION` or `IN_REVIEW`, else `ERR_ADOPTION_CYCLE_STATE_INVALID`. A `reason` of `ABANDON` is available only while the submission is `DRAFT`, else `ERR_SUBMISSION_STATE_INVALID`, and moves `review_status` to `WITHDRAWN`, a terminal state: a withdrawn submission is read-only, and subsequent attempts to add correlations, ship samples or file against it are all refused with `ERR_SUBMISSION_STATE_INVALID`. The same `WITHDRAWN` outcome arrives without any client request when a cycle advances from `OPEN` to `CLOSED_FOR_SUBMISSION` while the submission is still `DRAFT`.

### 3.6. Pricing Submission, Contract Terms and Bundling

Price is filed separately from content, and the submission's `pricing_status` dimension tracks it independently: `UNPRICED` at the start, `PRICE_FILED` once a proposal is on the table, and `PRICE_APPROVED` or `PRICE_REJECTED` once the state has ruled. A `PricingManager` files a proposal naming the `submission_id` it belongs to, an optional `bundle_id` naming the ancillary bundle committed with the program — null means core-only pricing — a `base_price_cents` of at least 1 giving the year-one list price per print copy offered to the state, a `term_years` between 1 and 10 inclusive, an `annual_escalator_bps` between 0 and 500 inclusive giving the annual price escalator in basis points, a `projected_adoption_units` of at least 0 giving the units the publisher projects for the state, a `digital_seat_price_cents` of at least 1 giving the committed price per digital student seat, and the `expected_submission_version` required by Section 2.8. Filing requires the submission's `review_status` to be `FILED`, `SCHEDULED` or `PRESENTED`, else `ERR_SUBMISSION_STATE_INVALID`, and requires the cycle to be `OPEN`, `CLOSED_FOR_SUBMISSION` or `IN_REVIEW`, else `ERR_ADOPTION_CYCLE_STATE_INVALID`. The committed `term_years` may not exceed either the state's `multi_year_max_years` or the cycle's `contract_term_years` — that is, it must be at most the smaller of the two — else `ERR_TERM_YEARS_EXCEED_STATE_MAX`. When a `bundle_id` is supplied, the referenced bundle must belong to the submission's own edition, else `ERR_BUNDLE_TITLE_MISMATCH`, and must satisfy the three platform commitments of Section 2.11.

Three independent discounts are then selected from the filing's own numbers. The **volume discount** rewards scale: `volume_discount_pct` is 0.12 when `projected_adoption_units` is at least 20,000, otherwise 0.07 when it is at least 5,000, otherwise 0.00. The **term discount** rewards commitment: `term_discount_pct` is 0.06 when `term_years` is at least 5, otherwise 0.03 when it is at least 3, otherwise 0.00. The **bundle discount** rewards breadth of the ancillary package: `bundle_discount_pct` is 0.00 when no `bundle_id` was supplied; otherwise it is 0.09 when the referenced bundle's `component_count` is at least 4, 0.05 when that count is at least 2, and 0.00 for a single-component bundle. The three are then added together and capped: `total_discount_pct` is the lesser of 0.20 and that sum, so no filing can ever discount more than a fifth of list regardless of how the tiers stack.

The net price is built year by year, and the **order of rounding is part of the contract**. Let the yearly escalation multiplier be 1 plus `annual_escalator_bps` divided by 10,000, carried exactly with no intermediate rounding. The price of contract year one is `base_price_cents` multiplied by 1 minus `total_discount_pct`; the price of contract year two is that same product multiplied once by the escalation multiplier; year three multiplies by the escalation multiplier twice; and in general the price of contract year *y* is `base_price_cents`, multiplied by the escalation multiplier raised to the power of one less than *y*, multiplied by 1 minus `total_discount_pct`. **Each year's price is rounded half up to whole cents individually, and only then are the years added together** to give `net_state_price_cents`. Summing the exact unrounded yearly decimals and rounding once at the end is wrong and can differ from the correct answer by as much as one cent for every year of the term after the first. Finally, `avg_annual_price_cents` is `net_state_price_cents` divided by `term_years`, rounded half up to a whole cent; this is the contracted per-copy price districts will pay. No other proposal of the submission participates in this computation.

Once the net price is known, the state's ceiling applies: when the state's `price_cap_cents` is not null and the computed `net_state_price_cents` exceeds it, the filing is refused with `ERR_PRICE_CAP_EXCEEDED`. An accepted filing is created with `status` `FILED`, `contract_locked` false and `decision_officer_ref` null, and moves the submission's `pricing_status` to `PRICE_FILED`. It also increments the submission's `version` by 1 — the mechanism Section 2.8 relies on.

Filing is also **create-with-supersede**. A publisher may re-file a price on a submission that is already `PRICE_FILED`, `PRICE_APPROVED` or `PRICE_REJECTED`, and the new filing moves the `pricing_status` back to `PRICE_FILED`. Every prior proposal of that submission whose `status` is `FILED` or `APPROVED` and whose `contract_locked` is false moves to `SUPERSEDED`. A prior proposal whose `contract_locked` is true, however, can never be superseded, and the attempt to file over it is refused outright with `ERR_CONTRACT_LOCKED`.

The state rules on a filed proposal through its own `StateAdoptionOfficer`, supplying a `verdict` and an optional `reason`. A `verdict` of `APPROVE` moves the proposal's `status` from `FILED` to `APPROVED` and the submission's `pricing_status` to `PRICE_APPROVED`; a `verdict` of `REJECT` moves the `status` from `FILED` to `REJECTED` and the `pricing_status` to `PRICE_REJECTED`. Either way, `decision_officer_ref` records the deciding officer's `X-User-ID`. A decision on a proposal that is not `FILED` is refused with `ERR_PRICING_PROPOSAL_STATE_INVALID`. Proposals can be listed and filtered by `submission_id`, `bundle_id`, `status` and `contract_locked`.

`contract_locked` deserves its own statement, because it is the system's only irreversible commercial flag. It becomes true in exactly two situations: when a district order is confirmed against this proposal while the proposal is `APPROVED`, and when the submission reaches `ADOPTED` or `ADOPTED_WITH_CONDITIONS` with this proposal `APPROVED`. Once true it is never cleared — cancelling the district order that locked it does **not** release the lock, because the signed contract existed.

### 3.7. Public Comment and the Compliance Score

Once a submission is filed, the public may comment on it, and every comment starts a clock the publisher must beat. A `PublicCommenter` or the state's own `StateAdoptionOfficer` files a comment against a submission, supplying a `commenter_ref` of 1 to 60 characters identifying the commenter for the state record, a `category` from `ERROR_OF_FACT`, `BIAS_CONCERN`, `PROHIBITED_CONTENT` and `OTHER`, a `severity` from `MINOR`, `MAJOR` and `CRITICAL`, and a `body` of 10 to 2,000 characters. The comment's `submission_id` comes from the path and its `status` starts at `OPEN`, with `responded_at`, `response_body` null and `was_overdue_at_response` false. Its `response_due_at` is computed as the comment's own `created_at` plus the state's `comment_response_days` converted to seconds at 86,400 seconds per day. Filing a comment immediately recomputes the submission's `unresolved_critical_count`, `compliance_score` and `adoption_blocked`. Comments of a submission can be listed and filtered by `status`, `severity` and `category`.

A comment is **overdue** when the logical clock stands at or after its `response_due_at`; the boundary is inclusive, so a response landing exactly on the deadline instant is late. Step one of the epoch sweep is what actually enforces this: an `OPEN` comment that has become overdue moves to `ESCALATED` and has `was_overdue_at_response` set to true, and the submission's `overdue_response_count` and — for a `CRITICAL` comment — `unresolved_critical_count` are recomputed, followed by `compliance_score` and a re-derivation of `adoption_blocked` that may in turn cancel `RESERVED` slots through step three of the same sweep.

The `PublisherEditor` answers a comment by publishing a `response_body`. The response is accepted from either `OPEN` or `ESCALATED`, moves the comment's `status` to `RESPONDED` — the terminal state — and sets `responded_at` to the logical clock. It requires the submission's `review_status` to be `FILED`, `SCHEDULED` or `PRESENTED`, else `ERR_SUBMISSION_STATE_INVALID`, and it requires the comment not to have been answered already, else `ERR_PUBLIC_COMMENT_STATE_INVALID`. Answering from `OPEN` sets `was_overdue_at_response` to true when the comment had already escalated or when the logical clock stands at or after `response_due_at`, and to false otherwise; answering from `ESCALATED` leaves `was_overdue_at_response` true, since the lateness is already a matter of record. Answering an `OPEN` comment recomputes `unresolved_critical_count`, `overdue_response_count`, `compliance_score` and `adoption_blocked`; answering an `ESCALATED` comment decrements `unresolved_critical_count` when the comment's `severity` is `CRITICAL`, leaves `overdue_response_count` unchanged — the escalation is already counted there — and recomputes `compliance_score` and `adoption_blocked`.

The two comment counters have exact definitions independent of any single event. `unresolved_critical_count` is the number of the submission's comments whose `severity` is `CRITICAL` and whose `status` is `OPEN` or `ESCALATED`. `overdue_response_count` is the number whose `status` is `ESCALATED`, plus the number whose `status` is `RESPONDED` and whose `was_overdue_at_response` is true. `category` never filters either counter; every comment of the submission is in scope regardless of category, and `severity` narrows only the critical counter.

**Compliance** is the single number the state and the publisher both watch. Two derived sets feed it. The **neutralised prohibited tags** are the `topic_code` values of every content edit for this edition and this state whose `edit_type` is `REMOVE_PROHIBITED_TAG` and whose `status` is `APPLIED` — proposed or approved edits do not count, only applied ones. The **supplied topics** are the edition's current `content_tags` together with the `topic_code` values of every content edit for this edition and this state whose `edit_type` is `ADD_REQUIRED_TOPIC` and whose `status` is `APPLIED`. From those, `prohibited_hit_count` is the number of the state's `prohibited_content_tags` that are present in the edition's `content_tags` and are not in the neutralised set, and `missing_required_topic_count` is the number of the state's `required_topics` that are absent from the supplied topics.

The score itself starts at 100 and is docked for each defect: 25 points for every prohibited-tag hit, 10 points for every missing required topic, 15 points for every unresolved critical comment, and 5 points for every overdue response. `compliance_score` is that result, floored at 0 — it never goes negative no matter how many defects accumulate. Finally, `adoption_blocked` is true when any of three conditions holds: `compliance_score` is strictly below 70, or `prohibited_hit_count` is greater than 0, or `content_pin_stale` is true. The threshold test is strict, so a score of exactly 70 does not block, while 69 does. Note that a single prohibited-tag hit blocks adoption on its own, independently of the score — a submission carrying one prohibited tag and nothing else scores 75 and is still blocked.

### 3.8. The Review Committee: Panels, Presentation Slots, Ballots and the Tally

A `CommitteePanel` is one sitting of a state's review committee, seated for a cycle by that state's `StateAdoptionOfficer`. The panel names its `cycle_id`, a `panel_label` of 1 to 60 characters, a `session_start_at` and a `session_end_at` that must be strictly after it, a `buffer_minutes` between 0 and 60 inclusive that defaults to 10 and states the mandatory turnover gap between two consecutive presentations, a `member_count` between 1 and 25 inclusive giving the number of seated members, and a `quorum_required` between 1 and `member_count` inclusive giving the minimum counted votes needed before a slot may be tallied. The panel also carries a `slot_minutes_capacity`: a policy cap, in whole minutes, on the total presentation time the panel will seat. When the field is omitted it defaults to the whole number of minutes between `session_start_at` and `session_end_at`; when supplied it must be at least 1 and at most that same whole-minute session length, and a value above the session length is refused with `ERR_INVALID_REQUEST`. Setting it below the session length is the ordinary way a panel reserves time for deliberation rather than presentation. Panels are born `SCHEDULED` with `reserved_minutes` at 0.

Reserving a `PresentationSlot` is how a filed submission gets a hearing, and it is again the state's `StateAdoptionOfficer` who does it. The reservation names the `submission_id` being presented, a `start_at` that is inclusive, an `end_at` strictly after it that is treated as inclusive for buffer arithmetic, and the `expected_panel_version` of Section 2.8. The slot's `panel_id` comes from the path, its `status` starts at `RESERVED`, its `tally_outcome` starts at `PENDING`, its `recommend_ratio` starts null, its `counted_vote_count` starts at 0, and its `duration_minutes` is computed as the whole number of minutes between `start_at` and `end_at`.

Four scheduling rules guard a reservation, in the order Section 2.6 fixes. The panel must still be `SCHEDULED`, else `ERR_COMMITTEE_PANEL_STATE_INVALID` — once a session is open, no new slot may be added. The submission must be `FILED`, else `ERR_SUBMISSION_STATE_INVALID`, and its `content_pin_stale` must be false, else `ERR_CONTENT_PIN_STALE`. The requested window must lie inside the panel's session, at or after `session_start_at` and at or before `session_end_at`, else `ERR_SLOT_OUTSIDE_SESSION`. The **buffered closed-interval rule** then compares the new window against every existing slot of the panel whose `status` is `RESERVED`, `PRESENTED`, `TALLIED` or `NO_SHOW`: the new slot is acceptable only if, for each such existing slot, the new `start_at` is at or after that slot's `end_at` advanced by `buffer_minutes`, **or** the new `end_at` advanced by `buffer_minutes` is at or before that slot's `start_at`. Any existing slot that satisfies neither alternative produces `ERR_SLOT_BUFFER_CONFLICT`. Note that a `NO_SHOW` slot still occupies the session record for this purpose, while a `CANCELLED` slot does not. Finally, the panel's minute budget must accommodate the slot: the panel's current `reserved_minutes` plus the new slot's `duration_minutes` must be at most `slot_minutes_capacity`, else `ERR_PANEL_CAPACITY_EXCEEDED` — and because `slot_minutes_capacity` may sit well below the wall-clock session length, a window that comfortably fits inside the session can still be refused on budget.

An accepted reservation adds the slot's `duration_minutes` to the panel's `reserved_minutes` and increments the panel's `version` by 1, and moves the submission's `review_status` from `FILED` to `SCHEDULED` while incrementing the cycle's `scheduled_submission_count` by 1. Slots can be listed and filtered by `panel_id`, `submission_id`, slot `status` and `tally_outcome`.

Opening a panel session moves the panel from `SCHEDULED` to `IN_SESSION` and requires three things of the acting officer's state: the cycle must be `IN_REVIEW`, else `ERR_ADOPTION_CYCLE_STATE_INVALID`, and the logical clock must have reached `session_start_at`, else `ERR_PANEL_SESSION_NOT_DUE`. From that point the panel's slots become presentable and further reservations are refused.

Presenting a slot moves it from `RESERVED` to `PRESENTED` and simultaneously moves its submission's `review_status` from `SCHEDULED` to `PRESENTED`. Three preconditions apply: the panel must be `IN_SESSION`, else `ERR_COMMITTEE_PANEL_STATE_INVALID`; the logical clock must have reached the slot's `start_at`, else `ERR_SLOT_NOT_STARTED`; and the submission's `content_pin_stale` must be false, else `ERR_CONTENT_PIN_STALE` — a submission whose edition changed between reservation and hearing cannot be heard.

Balloting is the `ReviewCommitteeMember`'s act, permitted only while the slot is `PRESENTED`. A ballot declares a `vote` from `RECOMMEND`, `RECOMMEND_WITH_CONDITIONS`, `REJECT` and `ABSTAIN`, together with a `rationale` of 5 to 500 characters for the public record. The ballot's `slot_id` comes from the path and its `member_user_id` from the acting `X-User-ID`. **Ballots are an append-only log**: a member who changes position simply casts another ballot, and the server assigns each new ballot a `sequence_no`, a monotonic per-slot integer starting at 1, and sets `superseded` to true on every earlier ballot of that same member on that same slot. The ballot log can be listed in full, superseded entries included, filtered by `vote` and by `superseded`.

**Tallying** projects that log into a recommendation, and it is performed by the state's `StateAdoptionOfficer` on a `PRESENTED` slot of an `IN_SESSION` panel. The projection keeps exactly one ballot per distinct `member_user_id`: the one with the latest `created_at`, and among ballots tied on `created_at` the one with the higher `sequence_no` — never the one with any particular `id`. The number of surviving ballots, abstentions included, is `counted_vote_count`. If `counted_vote_count` is below the panel's `quorum_required`, the tally is refused with `ERR_QUORUM_NOT_MET`. The counted ballots whose `vote` is not `ABSTAIN` form the ratio denominator; if there are none — every counted member abstained — the tally is refused with `ERR_NO_COUNTABLE_VOTES`.

Otherwise a weighted recommendation total is formed: each counted `RECOMMEND` ballot contributes 1, and each counted `RECOMMEND_WITH_CONDITIONS` ballot contributes one half. `recommend_ratio` is that total divided by the number of counted non-abstaining ballots, rounded half up to 4 decimal places. When `recommend_ratio` is at or above 0.6667, the slot's `tally_outcome` is `RECOMMEND_WITH_CONDITIONS` if at least one counted ballot was `RECOMMEND_WITH_CONDITIONS`, and `RECOMMEND` otherwise; when `recommend_ratio` is below 0.6667, the `tally_outcome` is `REJECT`. The comparison is inclusive, which matters at the obvious boundary: a two-thirds ratio rounds to 0.6667 and therefore recommends. The slot's `status` moves from `PRESENTED` to `TALLIED`, a terminal slot state.

The tally then branches, and the three branches carry different consequences. A `tally_outcome` of `RECOMMEND` moves the submission's `review_status` from `PRESENTED` to `ADOPTED` **provided every adoption gate is met**; a `tally_outcome` of `RECOMMEND_WITH_CONDITIONS` does the same but lands on `ADOPTED_WITH_CONDITIONS`. The adoption gates are four: the submission's `pricing_status` must be `PRICE_APPROVED`, its `verified_coverage_pct` must be at least the state's `min_verified_coverage_pct`, its `adoption_blocked` must be false, and its `unresolved_critical_count` must be zero. When adoption succeeds, the edition's `adopted_state_codes` gains the state's `state_code`, the edition's `status` moves from `DRAFT` to `ACTIVE` if it happened still to be `DRAFT`, the submission's `APPROVED` pricing proposal sets `contract_locked` to true, the cycle's `adopted_count` increases by 1 and its `submission_count` decreases by 1.

A `tally_outcome` of `REJECT` — and equally a recommending outcome with **any** one of the four adoption gates unmet — moves the submission's `review_status` from `PRESENTED` to `NOT_ADOPTED`. In that case `adopted_state_codes` is left untouched, every pricing proposal of the submission keeps `contract_locked` false, and only the cycle's `submission_count` decreases by 1. The same `NOT_ADOPTED` outcome arrives without any client request when the cycle advances from `PUBLIC_COMMENT` to `DECIDED` while the submission is still `FILED`, `SCHEDULED` or `PRESENTED`.

Closing a panel session moves the panel from `IN_SESSION` to `CLOSED`, its terminal state, and is refused with `ERR_PRESENTATION_SLOT_STATE_INVALID` while any slot of the panel is still `PRESENTED` — a submission that was heard must be tallied before the hearing can be closed out. On close, every slot still `RESERVED` moves to `NO_SHOW`, and each affected submission whose remaining slots include none in `RESERVED`, `PRESENTED` or `TALLIED` moves its `review_status` from `SCHEDULED` back to `FILED`, decrementing its cycle's `scheduled_submission_count`. Unlike a cancellation, a no-show leaves the panel's `reserved_minutes` **unchanged**: the minutes were spent whether or not the publisher showed up.

### 3.9. District Sales: Quoting, Confirming, Fulfilling and Cancelling

Selling into districts is the `SalesRep`'s work, and the rules differ by the state's `adoption_model`. A quote names the `district_ref` identifying the district, of 1 to 60 characters, the `state_id` the district sits in, the `title_id` ordered, an optional `pricing_proposal_id` naming the approved state price filing the order draws on, a `print_units` of at least 0 and a `digital_seats` of at least 0. The new order is `QUOTED` with `created_by_user_id` set from the acting `X-User-ID`, `allocated_units` at 0, `contracted_tcv_cents` null and `confirmed_by_user_id` null. Quoting requires the edition to have been released, else `ERR_TITLE_NOT_RELEASED`, and requires it not to be `SUNSET`, else `ERR_TITLE_SUNSET`. No inventory moves at quote time. Orders can be listed and filtered by `state_id`, `title_id`, `pricing_proposal_id`, `district_ref` and order `status`.

Total contract value is computed twice from the same shape of arithmetic, once at quote time into `quoted_tcv_cents` and once at confirmation into `contracted_tcv_cents`, and the two variants deliberately disagree. The computation first fixes a **unit price** and a **seat price**. In the quoted variant the unit price is the edition's own `list_price_cents`. In the contracted variant the unit price is the attached proposal's `avg_annual_price_cents` when a `pricing_proposal_id` is present, and the edition's `list_price_cents` when it is not. The seat price, in both variants, is the attached proposal's `digital_seat_price_cents` when a `pricing_proposal_id` is present, and otherwise a default open-territory seat price of 1,200 cents — twelve dollars per student seat.

From those, the print subtotal is the unit price multiplied by `print_units`, the digital subtotal is the seat price multiplied by `digital_seats`, and the **pre-freight total** is their sum. Freight is then decided **on the pre-freight total, never on the final total**: `freight_surcharge_cents` is 0 when the pre-freight total is at or above the freight waiver threshold of 2,500,000 cents — that is, twenty-five thousand dollars — and otherwise is the print subtotal multiplied by a freight rate of 0.015, rounded half up to a whole cent. Testing the waiver against the post-freight total instead would flip the outcome for orders whose pre-freight total sits just below the threshold, so the evaluation order is fixed. Next, an adopted-list rebate applies **only** in the contracted variant and **only** when the state's `adoption_model` is `ADOPTION_LIST`: it is the print subtotal multiplied by 0.02, rounded half up to a whole cent; in every other case the rebate is 0. Freight and rebate are each rounded independently. The stored total is the pre-freight total plus `freight_surcharge_cents` minus the rebate, and `freight_surcharge_cents` on the order always reflects the most recently computed total. No other order participates in either computation. Because the contracted variant swaps in the state-approved unit price and applies the adopted-list rebate that the quote ignores, identical inputs routinely yield a `contracted_tcv_cents` different from the `quoted_tcv_cents` the district first saw.

Confirmation moves the order from `QUOTED` to `CONFIRMED` and is the most heavily guarded operation in the sales flow. The confirming rep's `X-User-ID` must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The edition must not be `SUNSET`, else `ERR_TITLE_SUNSET`. In an `ADOPTION_LIST` state three further conditions apply: the order must carry a `pricing_proposal_id`, else `ERR_PRICING_PROPOSAL_REQUIRED`; that proposal's `status` must be `APPROVED`, else `ERR_PRICING_PROPOSAL_STATE_INVALID`; and the edition's `adopted_state_codes` must contain the district's own `state_code`, else `ERR_TITLE_NOT_ON_ADOPTED_LIST`. In an `OPEN_TERRITORY` state none of those three applies and a district may buy directly. Finally, the edition's `on_hand_units` must be at least the order's `print_units`, else `ERR_INSUFFICIENT_PRINT_INVENTORY`.

A confirmation writes `contracted_tcv_cents` and `freight_surcharge_cents` from the contracted variant, records `confirmed_by_user_id`, sets `allocated_units` to `print_units`, and moves the stock: the edition's `on_hand_units` decreases by `print_units` and its `committed_units` increases by the same amount. And when the order names a proposal whose `status` is `APPROVED`, that proposal sets `contract_locked` to true — the signed district contract freezes the price filing, which is why no later filing can supersede it and why a later cancellation does not release it.

Fulfilment moves a `CONFIRMED` order to `FULFILLED`, its terminal state, decreasing the edition's `committed_units` by `allocated_units` and increasing its `fulfilled_units` by the same amount. `allocated_units` itself is left as it stands, recording what shipped, and the order becomes read-only.

Cancellation, which requires a `reason`, is accepted from either `QUOTED` or `CONFIRMED` and lands on `CANCELLED`, a terminal state. From `QUOTED` there is nothing to unwind, since `allocated_units` is already 0. From `CONFIRMED` the commitment is released: the edition's `committed_units` decreases by `allocated_units`, its `on_hand_units` increases by the same amount, `allocated_units` becomes 0, `contracted_tcv_cents` is reset to null and `freight_surcharge_cents` to 0. Either way the print-unit ledger identity of Section 2.10 comes out unchanged, and — as stated above — a proposal that was locked by this order stays locked.

## 4. Endpoint Definitions

Operations that mint a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`. All paths are mounted at the root of the service.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/state-profiles` | Register an adopting state with its submission requirements, content rules and pricing limits | PlatformAdmin |
| GET | `/state-profiles/{id}` | Read one state profile | PlatformAdmin, StateAdoptionOfficer, PublisherEditor, EditorialDirector, PricingManager, SalesRep, ReviewCommitteeMember |
| POST | `/state-profiles/{id}/standards` | Add one academic standard to the state's framework for a subject and grade band | PlatformAdmin, StateAdoptionOfficer |
| GET | `/state-profiles/{id}/standards` | List the state's framework standards, optionally narrowed to one subject | PlatformAdmin, StateAdoptionOfficer, PublisherEditor, EditorialDirector, ReviewCommitteeMember |
| POST | `/adoption-cycles` | Open an adoption cycle for a subject rotation slot with its calendar of phase timestamps | StateAdoptionOfficer |
| GET | `/adoption-cycles` | List adoption cycles filtered by state, subject or phase | PlatformAdmin, StateAdoptionOfficer, PublisherEditor, EditorialDirector, PricingManager, ReviewCommitteeMember, SalesRep |
| GET | `/adoption-cycles/{id}` | Read one adoption cycle with its phase and submission counters | PlatformAdmin, StateAdoptionOfficer, PublisherEditor, EditorialDirector, PricingManager, ReviewCommitteeMember, SalesRep |
| POST | `/adoption-cycles/{id}/phase-advance` | Advance the cycle exactly one phase when the logical clock has reached that phase's timestamp, running the shared epoch sweep | StateAdoptionOfficer |
| GET | `/adoption-cycles/{id}/panels` | List the review committee panels seated for this cycle | PlatformAdmin, StateAdoptionOfficer, PublisherEditor, ReviewCommitteeMember |
| POST | `/titles` | Create a print program edition in draft with its seed content tags, page count and press signature capacity | PlatformAdmin, PublisherEditor |
| GET | `/titles/{id}` | Read one title with its content, page-budget and inventory counters | PlatformAdmin, PublisherEditor, EditorialDirector, PricingManager, SalesRep, StateAdoptionOfficer, ReviewCommitteeMember |
| POST | `/titles/{id}/release` | Release a draft edition so it may be submitted, priced and ordered | PublisherEditor |
| POST | `/titles/{id}/inventory-adjustments` | Receive print units into the warehouse or write units off, preserving the print-unit ledger identity | PlatformAdmin, EditorialDirector |
| POST | `/titles/{id}/revision-plan` | Plan, cancel or execute the next revision cycle of the edition against the adoption calendar | EditorialDirector |
| POST | `/titles/{id}/ancillary-bundles` | Define an ancillary bundle with its component count, digital seat price, rostering standard and accessibility and privacy commitments | PricingManager |
| GET | `/titles/{id}/ancillary-bundles` | List the ancillary bundles defined for this title | PlatformAdmin, PricingManager, PublisherEditor, StateAdoptionOfficer, SalesRep |
| POST | `/content-edits` | Propose a state-specific content change adding a required topic, removing a prohibited tag or substituting regional material | PublisherEditor |
| GET | `/content-edits` | List content edits filtered by title, state, type or workflow status | PlatformAdmin, PublisherEditor, EditorialDirector, StateAdoptionOfficer |
| GET | `/content-edits/{id}` | Read one content edit | PlatformAdmin, PublisherEditor, EditorialDirector, StateAdoptionOfficer |
| POST | `/content-edits/{id}/review` | Record the editorial director's approve or reject verdict on a proposed edit | EditorialDirector |
| POST | `/content-edits/{id}/resubmit` | Resubmit a rejected edit for another review round | PublisherEditor |
| POST | `/content-edits/{id}/apply` | Apply an approved edit to the edition, bumping the content revision and cascading staleness through submissions, slots and panels | EditorialDirector |
| POST | `/content-edits/{id}/revert` | Compensate an applied edit, restoring page count, page budget and content tags | EditorialDirector |
| POST | `/submissions` | Start a draft submission of one title into one state adoption cycle | PublisherEditor |
| GET | `/submissions` | List submissions filtered by cycle, title or either status dimension | PlatformAdmin, PublisherEditor, EditorialDirector, StateAdoptionOfficer, ReviewCommitteeMember, PricingManager |
| GET | `/submissions/{id}` | Read one submission with both status dimensions, coverage percentages and compliance counters | PlatformAdmin, PublisherEditor, EditorialDirector, StateAdoptionOfficer, ReviewCommitteeMember, PricingManager |
| POST | `/submissions/{id}/correlations` | Document one correlation entry mapping submitted content to a state standard with an evidence citation | PublisherEditor |
| GET | `/submissions/{id}/correlations` | List the submission's correlation entries with their committee verdicts | PlatformAdmin, PublisherEditor, ReviewCommitteeMember, StateAdoptionOfficer |
| POST | `/submissions/{id}/correlations/{entryId}/verdict` | Record a committee member's verdict on one correlation entry's evidence citation | ReviewCommitteeMember |
| POST | `/submissions/{id}/file` | File the submission with the state, pinning the title's content revision and enforcing every submission requirement | PublisherEditor |
| POST | `/submissions/{id}/withdraw` | Withdraw a submission, either back to draft for revision or abandoning it entirely | PublisherEditor |
| POST | `/submissions/{id}/sampling-shipments` | Ship print sample copies toward the state's sampling requirement, drawing them out of on-hand inventory | PublisherEditor |
| POST | `/submissions/{id}/public-comments` | Record a public comment against a filed submission, starting the response clock | PublicCommenter, StateAdoptionOfficer |
| GET | `/submissions/{id}/public-comments` | List the public comments filed against this submission | PlatformAdmin, PublisherEditor, StateAdoptionOfficer, ReviewCommitteeMember, PublicCommenter |
| POST | `/public-comments/{id}/response` | Publish the publisher's response to a public comment, on time or late | PublisherEditor |
| POST | `/committee-panels` | Seat a review committee panel for a cycle with its session window, turnover buffer and quorum | StateAdoptionOfficer |
| GET | `/committee-panels/{id}` | Read one panel with its capacity and reservation counters | PlatformAdmin, StateAdoptionOfficer, ReviewCommitteeMember, PublisherEditor |
| POST | `/committee-panels/{id}/slots` | Reserve a presentation slot for a filed submission inside the panel's session, honouring the turnover buffer and the panel's minute budget | StateAdoptionOfficer |
| POST | `/committee-panels/{id}/open-session` | Open the panel session once the cycle is in review and the clock has reached the session start | StateAdoptionOfficer |
| POST | `/committee-panels/{id}/close-session` | Close the panel session, marking still-reserved slots as no-shows | StateAdoptionOfficer |
| GET | `/presentation-slots` | List presentation slots filtered by panel, submission or slot status | PlatformAdmin, StateAdoptionOfficer, ReviewCommitteeMember, PublisherEditor |
| GET | `/presentation-slots/{id}` | Read one presentation slot with its tally outcome and ratio | PlatformAdmin, StateAdoptionOfficer, ReviewCommitteeMember, PublisherEditor |
| POST | `/presentation-slots/{id}/present` | Mark the submission as presented to the seated committee at its slot | StateAdoptionOfficer |
| POST | `/presentation-slots/{id}/votes` | Cast or recast a committee member's ballot on a presented submission | ReviewCommitteeMember |
| GET | `/presentation-slots/{id}/votes` | List the ballot log of a slot including superseded ballots | PlatformAdmin, StateAdoptionOfficer, ReviewCommitteeMember |
| POST | `/presentation-slots/{id}/tally` | Tally the slot's ballot log into a committee recommendation and branch the submission to its terminal review status | StateAdoptionOfficer |
| POST | `/pricing-proposals` | File a multi-year price and contract-term proposal for a submission, superseding any live proposal on the same submission | PricingManager |
| GET | `/pricing-proposals` | List pricing proposals filtered by submission, bundle or review status | PlatformAdmin, PricingManager, StateAdoptionOfficer, SalesRep |
| GET | `/pricing-proposals/{id}` | Read one pricing proposal with its computed discounts and net price | PlatformAdmin, PricingManager, StateAdoptionOfficer, SalesRep |
| POST | `/pricing-proposals/{id}/decision` | Record the state's approval or rejection of a filed price proposal | StateAdoptionOfficer |
| POST | `/district-orders` | Quote a district order for a released title, at list price in open territory or against an approved state price filing | SalesRep |
| GET | `/district-orders` | List district orders filtered by state, title, price filing or order status | PlatformAdmin, SalesRep, PricingManager, StateAdoptionOfficer |
| GET | `/district-orders/{id}` | Read one district order with both total contract values | PlatformAdmin, SalesRep, PricingManager, StateAdoptionOfficer |
| POST | `/district-orders/{id}/confirm` | Confirm a quoted order against the adopted list or open territory rules, recomputing the contracted value and committing inventory | SalesRep |
| POST | `/district-orders/{id}/fulfill` | Ship a confirmed order, moving committed print units to fulfilled | SalesRep |
| POST | `/district-orders/{id}/cancel` | Cancel a quoted or confirmed order, releasing any committed print units back to on hand | SalesRep |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock, which every deadline, window, escalation and phase check reads | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_STATE_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STATE_PROFILE_NOT_FOUND` | 404 Not Found |
| `ERR_ADOPTION_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTENT_EDIT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_CORRELATION_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITTEE_PANEL_NOT_FOUND` | 404 Not Found |
| `ERR_PRESENTATION_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_PRICING_PROPOSAL_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRICT_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PUBLIC_COMMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_SUBMISSION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PANEL_VERSION` | 412 Precondition Failed |
| `ERR_ADOPTION_CYCLE_STATE_INVALID` | 409 Conflict |
| `ERR_SUBMISSION_STATE_INVALID` | 409 Conflict |
| `ERR_CONTENT_EDIT_STATE_INVALID` | 409 Conflict |
| `ERR_TITLE_STATE_INVALID` | 409 Conflict |
| `ERR_TITLE_SUNSET` | 409 Conflict |
| `ERR_TITLE_NOT_RELEASED` | 409 Conflict |
| `ERR_COMMITTEE_PANEL_STATE_INVALID` | 409 Conflict |
| `ERR_PRESENTATION_SLOT_STATE_INVALID` | 409 Conflict |
| `ERR_PRICING_PROPOSAL_STATE_INVALID` | 409 Conflict |
| `ERR_DISTRICT_ORDER_STATE_INVALID` | 409 Conflict |
| `ERR_PUBLIC_COMMENT_STATE_INVALID` | 409 Conflict |
| `ERR_CYCLE_NOT_OPEN_FOR_SUBMISSION` | 409 Conflict |
| `ERR_CONTENT_PIN_STALE` | 409 Conflict |
| `ERR_EDIT_REVERT_BLOCKED` | 409 Conflict |
| `ERR_REVISION_CONFLICTS_WITH_OPEN_ADOPTION` | 409 Conflict |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SLOT_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_PHASE_NOT_DUE` | 409 Conflict |
| `ERR_PANEL_SESSION_NOT_DUE` | 409 Conflict |
| `ERR_SLOT_NOT_STARTED` | 409 Conflict |
| `ERR_DUPLICATE_SUBMISSION` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_EDIT_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_CONTRACT_LOCKED` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_PANEL_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PAGE_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_PRINT_INVENTORY` | 409 Conflict |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_SLOT_OUTSIDE_SESSION` | 422 Unprocessable Entity |
| `ERR_PROHIBITED_CONTENT_PRESENT` | 422 Unprocessable Entity |
| `ERR_REQUIRED_TOPIC_MISSING` | 422 Unprocessable Entity |
| `ERR_ACCESSIBILITY_COMMITMENT_MISSING` | 422 Unprocessable Entity |
| `ERR_PRIVACY_ADDENDUM_MISSING` | 422 Unprocessable Entity |
| `ERR_ROSTERING_STANDARD_UNSUPPORTED` | 422 Unprocessable Entity |
| `ERR_STANDARD_NOT_IN_FRAMEWORK` | 422 Unprocessable Entity |
| `ERR_BUNDLE_TITLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRICING_PROPOSAL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_TITLE_NOT_ON_ADOPTED_LIST` | 422 Unprocessable Entity |
| `ERR_CORRELATION_SET_EMPTY` | 422 Unprocessable Entity |
| `ERR_FOCUS_STANDARD_UNCOVERED` | 422 Unprocessable Entity |
| `ERR_COVERAGE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_SAMPLING_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_TERM_YEARS_EXCEED_STATE_MAX` | 422 Unprocessable Entity |
| `ERR_PRICE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_COUNTABLE_VOTES` | 422 Unprocessable Entity |
| `ERR_TITLE_NOT_RELEASABLE` | 422 Unprocessable Entity |
