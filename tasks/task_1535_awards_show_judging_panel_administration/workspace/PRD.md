# Awards Show Judging API — Product Requirements Document

## 1. Introduction

An industry awards program lives or dies on trust: entrants must believe that fees are assessed fairly, that judges score without conflicts of interest, that results stay sealed until the ceremony, and that any irregularity can be appealed and audited after the fact. This document specifies the Awards Show Judging API, the back-office system that administers one such program end to end — season and category definition with eligibility window rules, entry submission with tiered fees and material review, judge recruitment with conflict declarations and panel assignment, round-based scoring with normalization across panels, finalist notification under embargo, ceremony production and winner announcements, trophy and certificate fulfillment, and results appeals backed by a tamper-evident integrity audit.

All endpoints are mounted under the `/awards` prefix. The design rests on three pillars: a strict segregation of duties among program staff, entrants, judges, independent auditors, and the fulfillment vendor; a logical server clock that drives every window gate (submission, eligibility, acknowledgement, embargo, go-live); and an append-only, hash-chained audit log per season. Section 2 fixes the global contracts, Section 3 narrates the business workflows, Section 4 tabulates the endpoints, and Section 5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Six roles are recognized, spelled exactly as follows: `ProgramAdmin`, `Entrant`, `Judge`, `Auditor`, `FulfillmentVendor`, and `Anonymous`. A `ProgramAdmin` is awards program staff, configuring seasons, categories, and rounds, ruling on eligibility, locking panels and finalists, and running the ceremony. An `Entrant` is a submitting organization owning entries, materials, invoices, finalist acknowledgements, and appeals. A `Judge` is a scoring panelist who declares conflicts, confirms or recuses assignments, and submits ballots. An `Auditor` is an independent integrity officer who reviews appeals, retracts announcements, and reads audit logs. A `FulfillmentVendor` produces trophies and certificates, advancing fulfillment orders through the production pipeline. An `Anonymous` caller is a member of the public reading published, embargo-lifted results.

When `X-User-Role` is `Entrant`, `X-User-ID` is the `id` of the acting `Entrant`; ownership checks on any resource that references an `Entrant` — an entry's `entrant_id`, an appeal's `filed_by_entrant_id`, a finalist record's owning entrant — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Judge`, `X-User-ID` is likewise the `id` of the acting `Judge`, compared against the `judge_id` on assignments, scores, and declarations. When `X-User-Role` is `ProgramAdmin`, `Auditor`, `FulfillmentVendor`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `actor_id` on audit rows or as `decided_by` on an appeal) but does not compare it to any entity's `id`.

Missing or empty headers are rejected with `ERR_UNAUTHENTICATED` (401) on every endpoint except the clock-setting capability described in §2.6. A role attempting an operation outside its grant in §4 is rejected with `ERR_FORBIDDEN_ROLE` (403).

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

List endpoints paginate via query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Individual collections also expose domain filters (for example `status`, `standing`, or `entrant_id`); the filters available on each collection are named in the §3 narratives alongside the workflows that produce those collections.

### 2.4. Common Resource Properties

Full-tracking resources — seasons, categories, entrants, entries, invoices, judges, panel assignments, scoring rounds, finalist records, ceremonies, winner announcements, fulfillment orders, and appeals — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits captured at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that increments by one on every mutation of the resource, including cascaded mutations triggered by another resource's action (for example, proposing a panel assignment advances the round's `version`); every state-changing action endpoint on these resources increments the target's `version` by one and refreshes `updated_at`.

Four evidence-style record types — `EntryMaterial`, `ConflictDeclaration`, `Score`, and `AuditLog` — carry only `id` and `created_at`; both `updated_at` and `version` are absent on these four resources.

### 2.5. Validation Order and Error Precedence

Every request is evaluated against a fixed validation pipeline. Checks run in the order below, and the first failure short-circuits the remainder, so an earlier error always masks a later one.

1. Authentication: the `X-User-Role` and `X-User-ID` headers must be present and non-empty, otherwise `ERR_UNAUTHENTICATED` (401). This check applies to every endpoint except the clock-setting capability (§2.6).
2. Authorization: the role must be permitted for the endpoint per §4, otherwise `ERR_FORBIDDEN_ROLE` (403).
3. Payload well-formedness: required fields present, types correct, enum members valid, datetimes parseable, otherwise `ERR_INVALID_REQUEST` (400).
4. Path existence: path resources exist, validated left to right (§2.7), otherwise `ERR_NOT_FOUND` (404).
5. Body references: foreign-key identifiers carried in the request body (such as `entrant_id`, `judge_id`, or `category_id`) must resolve to existing resources, otherwise `ERR_REFERENCE_NOT_FOUND` (404).
6. Terminal-state guard: an action on an entity already in a terminal state is rejected with `ERR_ALREADY_TERMINAL` (409).
7. State gate: the target entity's state must permit the requested transition, and child-creating operations carry parent state gates — a ballot requires an `OPEN` round, an entry requires a season in `DRAFT` or `OPEN` with a `PUBLISHED` category, and a panel assignment requires a `CONFIGURING` round — otherwise `ERR_INVALID_STATE` (409).
8. Stale-version guard: on OCC-guarded writes the expected-version field must match the parent entity's current `version`, otherwise `ERR_STALE_VERSION` (412, §2.9).
9. Clock windows: the submission and late windows, the embargo lift, the acknowledgement window, and the go-live lead time — violations yield `ERR_OUTSIDE_WINDOW` (422).
10. Eligibility window at submission: `ERR_ELIGIBILITY_WINDOW` (422).
11. Ceremony interval overlap: `ERR_CEREMONY_OVERLAP` (422).
12. Scoring-round window gap: `ERR_ROUND_WINDOW_TOO_CLOSE` (422).
13. Conflict-of-interest bars: `ERR_CONFLICT_OF_INTEREST` (422).
14. Segregation of duties: `ERR_SEGREGATION_OF_DUTIES` (422).
15. Uniqueness: `ERR_DUPLICATE` (409).
16. Structural constraints: `ERR_CONSTRAINT_VIOLATION` (422).
17. Fiscal gates: `ERR_FISCAL_BLOCK` (402).
18. Panel completeness at lock: `ERR_PANEL_INCOMPLETE` (422).
19. Complete ballot at close: `ERR_INCOMPLETE_BALLOT` (422).
20. Score authorship: `ERR_REFERENTIAL_INTEGRITY` (422).
21. Aggregate integrity (orphan finalists, rank-1 winner): `ERR_REFERENTIAL_INTEGRITY` (422).
22. Appeal cap: `ERR_APPEAL_CAP_EXCEEDED` (422).
23. Embargo gate: `ERR_EMBARGO_ACTIVE` (403).
24. Audit hash-chain verification on read: `ERR_HASH_CHAIN_BROKEN` (409).

### 2.6. The Logical Clock and Time-Window Gates

The server keeps a logical clock rather than reading wall-clock time. Before any call to the clock-setting capability (`POST /awards/_clock/set_current_utc`, restricted to `ProgramAdmin`), the clock reads the fixed default `2026-08-01T00:00:00Z` and must never fall back to wall-clock time. The capability accepts a `to_iso8601` instant, returns the resulting `current_utc`, and then runs the clock sweep against everything the new instant crosses: sweeping past a season's late-submission deadline withdraws that season's lingering `DRAFT` entries; sweeping past an invoice's `due_at` flips the owing entrant to `DELINQUENT`; sweeping past a finalist's acknowledgement deadline auto-declines the notification; sweeping past `embargo_lifts_at` flips eligible finalist records to publicly visible.

Four families of window gates are evaluated against this clock, producing `ERR_OUTSIDE_WINDOW` unless a more specific error is named: the submission window and its 48-hour late extension; the 72-hour invoice due window; the finalist acknowledgement window governed by `ack_window_hours` (default 72); and the ceremony gates — the embargo lift instant and the go-live lead time governed by `go_live_lead_minutes` (default 30).

### 2.7. Nested Resource Retrieval

Paths that nest identifiers are validated in strict left-to-right order — season, then category, then entry, then round, then score, and so on. The request is rejected with `ERR_NOT_FOUND` (404) at the first identifier that does not resolve, before any child validation runs. A request for an entry under a non-existent category therefore fails on the category before the entry is ever consulted, and creation operations validate the parent's existence ahead of any payload rule.

### 2.8. Monetary and Scoring Precision

All fee and refund amounts are integer cents; no rounding occurs anywhere in the fiscal pipeline. Rubric weights are integer basis points: a category's `scoring_rubric` is an ordered list of criterion objects, each carrying a `criterion_code`, a `weight_bp`, and a `max_score`, and the `weight_bp` values must sum to exactly 10,000 — one hundred percent expressed in ten-thousandths. All computed score fields (`weighted_raw`, `z_intermediate`, `rank_among_judges_scores`, `normalized_score`, per-round entry composites, and `final_composite_score`) are carried to four decimal places with round-half-up applied at the steps named in §3.6; ranks such as `rank_among_judges_scores` may hold half-integer averages when ties share a rank. Judge reliability (`reliability_score_bp`) is an integer basis-point value between 0 and 10,000.

### 2.9. Optimistic Concurrency Control

Three child-creating writes are guarded against stale parent reads. Each requires a non-optional expected-version field carrying the client's last observed `version` of the parent entity:

- `POST /awards/scoring-rounds/{id}/panel-assignments` requires `expected_scoring_round_version` matching the target `ScoringRound`'s current `version`.
- `POST /awards/judges/{id}/conflict-declarations` requires `expected_judge_version` matching the target `Judge`'s current `version`.
- `POST /awards/scoring-rounds/{id}/scores` requires `expected_scoring_round_version` matching the target `ScoringRound`'s current `version`.

If the parent entity's `version` has advanced since the client last read it — because another writer proposed or confirmed an assignment, the judge's affiliation set or status changed, or a ballot was posted against the round — the write is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being merged against a stale baseline. A panel-capacity view or affiliation baseline captured at an older version is therefore never silently overwritten. Endpoints not listed here do not take a version field.

### 2.10. Embargo and Public Visibility

While a season is `FINALISTS_LOCKED` or `EMBARGOED` and the clock has not yet reached `embargo_lifts_at`, result data is embargo-protected. An `Anonymous` caller listing a category's finalists sees only records whose `embargo_visible` flag is true; reading an entry nulls its `final_composite_score` and `final_rank` for `Anonymous` callers; and embargo-protected reads of finalist or announcement data are otherwise denied with `ERR_EMBARGO_ACTIVE` (403). A finalist record's `embargo_visible` becomes true only when the clock has reached `embargo_lifts_at` and the season stands in `CEREMONY_LIVE` or `PUBLISHED`; the go-live transition, the publish-results transition, and the clock sweep are the three moments at which the server re-evaluates the flag, and publishing results sets `embargo_visible` on every finalist record unconditionally.

### 2.11. The Season Audit Chain and Integrity Posture

Each season accumulates an append-only `AuditLog`. The lifecycle transitions called out in §3 append a row recording the `actor_role` and `actor_id` taken from the request headers, a machine `action` name such as `SEASON_OPEN`, `ENTRY_SUBMIT`, `ROUND_NORMALIZED`, `WINNER_ANNOUNCED`, or `APPEAL_UPHELD`, the `target_type` and `target_id` of the mutated entity, and a structured `detail` payload capturing before-and-after values for integrity reconstruction. Rows are hash-chained for tamper evidence: each row's `hash_chain_prev` is the SHA-256 of the previous audit row in the same season, with the genesis row using sixty-four zero hex characters, and each row's `hash_chain_self` is the SHA-256 computed over the concatenation of `hash_chain_prev`, `action`, `target_id`, and the canonical form of `detail`. Reading a season's audit log — filterable by `target_type` and `target_id` — re-verifies the chain row by row; a mismatch flips the season's `integrity_flag` to `COMPROMISED` and the read fails with `ERR_HASH_CHAIN_BROKEN` (409).

A season's `integrity_flag` is a computed aggregate posture. It starts `CLEAN`; it moves to `UNDER_REVIEW` when an appeal is taken under review, when a scoring round is voided on appeal, or when a winner announcement is retracted; and it becomes `COMPROMISED` when hash verification fails. Denying an appeal returns the flag to `CLEAN` only when no other appeal in the season remains in `FILED` or `UNDER_REVIEW`.

## 3. Business Logic & Workflows

### 3.1. Configuring a Season and Its Categories

A `ProgramAdmin` opens a new awards cycle by creating a season with a globally unique `code` (one to forty characters, for example GALA-2026), a `title` of up to 120 characters, and the calendar that will govern everything downstream: `submission_opens_at`, `early_fee_ends_at` (no earlier than the opening instant and no later than the closing instant), `submission_closes_at`, and the work-product eligibility window bracketed by `eligibility_window_start` (inclusive) and `eligibility_window_end` (exclusive and strictly after the start). Optional creation parameters include `ceremony_scheduled_at` (which must be set before the ceremony can go live), `max_appeals_per_entry` (default 2), `refund_policy` (`FLAT_FEE` by default, or `EARLY_BIRD_FREE`), `ack_window_hours` (default 72), and `go_live_lead_minutes` (default 30). A season is born `DRAFT`, with `active_entries_count` at zero and `integrity_flag` `CLEAN`; `active_entries_count` is a derived count of the season's entries that are neither `WITHDRAWN` nor `DISQUALIFIED`, recomputed on every entry status change. Seasons can be listed with a `status` filter, and a duplicate `code` is rejected with `ERR_DUPLICATE`.

Beneath a season, a `ProgramAdmin` defines categories. Each carries a `code` unique within its season, a display `name`, optional `description` and entrant-facing `eligibility_rules_text`, the material and entry caps `min_materials` (default 1) and `max_entries_per_entrant` (default 3), the three fee tiers `early_fee_cents`, `standard_fee_cents`, and `late_fee_cents`, the judging parameters `panel_size` (default 5) and `finalist_slots` (default 3), and the `scoring_rubric` whose `weight_bp` values must sum to exactly 10,000. A category is created `DRAFT` and becomes visible to entrants when published. Publishing from `DRAFT` requires the parent season to be `DRAFT` or `OPEN`, the rubric weights to sum to exactly 10,000, a `panel_size` of at least 3, and at least one finalist slot — violations surface as `ERR_CONSTRAINT_VIOLATION` or `ERR_INVALID_STATE` — and appends a `CATEGORY_PUBLISH` audit row. A published category may be suspended while the season is `DRAFT`, `OPEN`, or `SUBMISSION_CLOSED`; suspension withdraws that category's `DRAFT` entries. Re-publishing a `SUSPENDED` category again requires the season to be `DRAFT` or `OPEN` and the rubric sum to hold. Once the season reaches `PUBLISHED` or `ARCHIVED`, a published category with no appeal in `FILED` or `UNDER_REVIEW` on any of its entries may be retired; `RETIRED` is terminal.

Opening the season — `DRAFT` to `OPEN` — requires at least one `PUBLISHED` category and a clock reading on or after `submission_opens_at` but strictly before `submission_closes_at`; a premature or tardy attempt fails with `ERR_OUTSIDE_WINDOW`, and success appends a `SEASON_OPEN` audit row. A season may also be cancelled outright from `DRAFT` or `OPEN`: cancellation is terminal (`CANCELLED`), withdraws every child entry not already `WITHDRAWN` or `DISQUALIFIED`, voids every `ISSUED` invoice, and appends `SEASON_CANCEL`.

### 3.2. Entrant Registration, Entries, and Materials

`ProgramAdmin` registers each submitting organization as an entrant with a `legal_name`, a unique `contact_email`, and a `country_code` given as an ISO 3166-1 alpha-2 code. New entrants stand in `GOOD` standing with `delinquent_since` unset and `lifetime_disqualifications` at zero. The entrant roster can be listed with a `standing` filter, and a duplicate `contact_email` is rejected with `ERR_DUPLICATE`.

An entrant drafts an entry inside a category with a payload containing the `entrant_id`, the work's `title`, and `work_completed_at`, the instant the work product was completed. Creation is gated on the parent category being `PUBLISHED` and the season being `DRAFT` or `OPEN` (otherwise `ERR_INVALID_STATE`), and the referenced entrant and category must exist (`ERR_REFERENCE_NOT_FOUND`). New entries are `DRAFT` with `payment_status` `UNPAID`, `revision_count` zero, `fee_waived` false, `fee_tier_applied` null, and `final_composite_score` and `final_rank` not yet computed. An entrant's own entries are listed under their entrant record, and program staff can list a category's entries filtered by `status` or `entrant_id`.

Supporting evidence attaches to an entry as materials. Each material names its `material_type` — one of `VIDEO`, `AUDIO`, `PDF`, `IMAGE`, or `URL` — a `uri` locating the asset, a declared `file_size_bytes` that may not exceed 104,857,600 bytes (100 MiB, enforced as `ERR_CONSTRAINT_VIOLATION`), and a 64-hex-character `checksum_sha256` that later feeds tamper-evidence review. Materials are born `PENDING`; a `ProgramAdmin` accepts or rejects each one, moving it to `ACCEPTED` or `REJECTED`, and only `ACCEPTED` materials count toward submission readiness. An entry's materials can be listed with a `status` filter.

### 3.3. Submission, Fee Assessment, and Invoices

Submission is the entrant's declaration that an entry is complete, and it is heavily gated. The entry must be `DRAFT`, its category `PUBLISHED`, and its season `OPEN`. The clock must not have passed the late deadline: submissions remain accepted for 48 hours after `submission_closes_at`, and any later attempt fails with `ERR_OUTSIDE_WINDOW`. The completed-work instant `work_completed_at` must fall within the season's eligibility window — on or after `eligibility_window_start` and strictly before `eligibility_window_end` — or the submission fails with `ERR_ELIGIBILITY_WINDOW`. The entry must hold at least the category's `min_materials` accepted materials, and the entrant must remain below the category's `max_entries_per_entrant` cap counted over that entrant's non-`WITHDRAWN` entries in the category; both violations surface as `ERR_CONSTRAINT_VIOLATION`. Finally, a `BARRED` entrant may not submit at all, and the attempt is refused with `ERR_FISCAL_BLOCK`.

A successful submission creates the entry's fee invoice in the same step. The fee tier is chosen by the clock at submission time: strictly before `early_fee_ends_at` the `EARLY` tier charges `early_fee_cents`; from `early_fee_ends_at` up to and including `submission_closes_at` the `STANDARD` tier charges `standard_fee_cents`; and inside the late window after `submission_closes_at` the `LATE` tier charges `late_fee_cents`. The boundary instants are pinned: a submission exactly at `early_fee_ends_at` pays the standard fee, one exactly at `submission_closes_at` still pays the standard fee, and one a single second later pays the late fee. The invoice is created `ISSUED` with the computed `amount_cents` and `tier`, and a `due_at` seventy-two hours after creation; the entry moves to `SUBMITTED`, its `payment_status` becomes `INVOICED`, `fee_tier_applied` records the tier, the season's `active_entries_count` is incremented by one, and an `ENTRY_SUBMIT` audit row is appended. Two facts are worth restating here: amounts are integer cents end to end, and an entry's `payment_status` is a parallel dimension that evolves independently of its lifecycle `status` across the values `UNPAID`, `INVOICED`, `PAID`, `REFUNDED`, and `WAIVED`.

A `ProgramAdmin` may grant a fee waiver while an entry is still `DRAFT`, which sets its `fee_waived` flag. When such an entry is submitted, no invoice is created at all: `payment_status` becomes `WAIVED`, and the entry passes straight through `SUBMITTED` to `UNDER_REVIEW` without waiting for settlement.

Settlement happens when the owning entrant pays the invoice. Only the entrant that owns the invoice's entry may pay it, and an invoice no longer in `ISSUED` is not payable; both failures are `ERR_FISCAL_BLOCK`. Payment stamps `paid_at`, moves the invoice to `PAID`, sets the entry's `payment_status` to `PAID`, and cascades a `SUBMITTED` entry into `UNDER_REVIEW` (a waived entry is already there, its `payment_status` remaining `WAIVED`). If the payment lands after `due_at` while the entrant is `DELINQUENT`, settlement also repairs their standing to `GOOD` and clears `delinquent_since`.

Standing is otherwise clock-driven. Whenever the clock sweep finds an entrant with an `ISSUED` invoice whose `due_at` has passed, a `GOOD` entrant becomes `DELINQUENT` with `delinquent_since` set to that instant; when no overdue invoice remains, a `DELINQUENT` entrant returns to `GOOD` and `delinquent_since` is cleared. Independently of invoices, an entrant whose `lifetime_disqualifications` reaches three is promoted to `BARRED`, which blocks new submissions regardless of payment hygiene. An entry's invoices can be listed with a `status` filter and read individually.

Withdrawal is the entrant's exit from a `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW` entry. Withdrawing voids any still-`ISSUED` invoice and returns `payment_status` to `UNPAID`. Withdrawing an entry whose invoice is `PAID` instead runs the refund calculation: the invoice becomes `REFUNDED` with `refund_cents` and `retained_cents` written, and `payment_status` becomes `REFUNDED`. The refund variant is selected by the season's `refund_policy`. Under `FLAT_FEE`, the program retains a flat 2,500-cent withdrawal fee and refunds the remainder of `amount_cents`, clamped at zero. Under `EARLY_BIRD_FREE`, an invoice whose `paid_at` precedes `early_fee_ends_at` is refunded in full with nothing retained, while any later payment retains 5,000 cents and refunds the remainder, again clamped at zero. The invariant that `refund_cents` plus `retained_cents` equals `amount_cents` always holds; when the clamped refund is zero, the retained amount equals the full invoice amount. Withdrawing a `SUBMITTED` or `UNDER_REVIEW` entry decrements the season's `active_entries_count` by one; withdrawing a `DRAFT` entry does not, since a draft was never counted.

### 3.4. Eligibility Review and Closing Intake

While the season is `OPEN` or `SUBMISSION_CLOSED`, program staff rule on each `UNDER_REVIEW` entry. Marking an entry eligible moves it to `ELIGIBLE` and appends `ENTRY_MARK_ELIGIBLE`; marking it ineligible moves it to `INELIGIBLE` and appends `ENTRY_MARK_INELIGIBLE`. An ineligibility ruling is deliberately not a refund event: the settled invoice stays `PAID`, no refund fires while the revision loop is open (refunds fire only on withdrawal or terminal disposition), and the season's `active_entries_count` is unchanged because an `INELIGIBLE` entry still counts as active — only `WITHDRAWN` and `DISQUALIFIED` entries leave the count.

The entrant may answer an ineligibility ruling by requesting a recheck, which returns the entry from `INELIGIBLE` to `UNDER_REVIEW`, increments `revision_count` by one, and re-uses the settled payment so `payment_status` remains `PAID`. The loop is capped: a recheck is accepted only while `revision_count` is below two — an entry may cycle at most twice — and only while the season is `OPEN` or `SUBMISSION_CLOSED`.

Intake closes when the `ProgramAdmin` closes submissions, and the same transition fires automatically if the clock is advanced past the late deadline, forty-eight hours after `submission_closes_at`. Closing requires the season to be `OPEN` and the clock to have reached `submission_closes_at`; it moves the season to `SUBMISSION_CLOSED`, sweeps every lingering `DRAFT` entry in the season to `WITHDRAWN`, recomputes `active_entries_count`, and appends `SEASON_CLOSE_SUBMISSIONS`.

Judging begins when two conditions hold across the season: every entry still `SUBMITTED` or `UNDER_REVIEW` has been resolved to `ELIGIBLE` or `INELIGIBLE`, and every `PUBLISHED` category has at least one `PANEL_LOCKED` scoring round whose `round_index` equals the minimum among that category's non-`VOIDED` rounds — panels must be locked in ascending round order. Beginning judging moves the season to `JUDGING`, cascades every `ELIGIBLE` entry to `IN_JUDGING`, and appends `SEASON_BEGIN_JUDGING`.

### 3.5. Judges, Conflicts of Interest, and Panel Assembly

A judge's lifecycle starts when a `ProgramAdmin` invites them with a `full_name`, a unique `email` (duplicates are `ERR_DUPLICATE`), and optional `expertise_tags` plus `affiliated_entrant_ids` — the list of entrants the judge is affiliated with, which feeds conflict seeding. New judges are `INVITED` with a `reliability_score_bp` of 10,000. The invited judge personally accepts or declines the invitation; declining is terminal (`DECLINED`). Accepting moves the judge to `ACCEPTED` and automatically seeds one conflict declaration per entry in `affiliated_entrant_ids`, with the season scope of each seeded declaration resolved per assignment. Program staff then activate an `ACCEPTED` judge — activation requires the judge to hold at least one declaration in `DECLARED` or `ACKNOWLEDGED` for the target season, or to have an empty affiliation list — moving them to `ACTIVE`. Suspending an `ACTIVE` judge removes every `PROPOSED` or `ACTIVE` panel assignment of theirs (to `REMOVED`) and re-evaluates panel completeness: any `PANEL_LOCKED` round that drops below its category's `panel_size` is demoted back to `CONFIGURING`. A `SUSPENDED` judge may be activated again, and a judge in `ACTIVE` or `SUSPENDED` may be retired only while holding no `ACTIVE` assignment in an `OPEN` round; `RETIRED` is terminal. Judges can be listed with a `status` filter.

Conflict declarations are the system's standing record of bias. A declaration is filed against a judge — by the judge personally or by a `ProgramAdmin` on their behalf — naming the `season_id`, the `entrant_id` the judge conflicts with, an optional `category_id` (a null category scope covers every category in the season), a `conflict_type` of `FINANCIAL`, `FAMILIAL`, `PROFESSIONAL`, `PERSONAL`, or `OTHER`, a `severity`, and an optional free-text `note`. Severity is decisive: a `HARD` conflict bars the judge from assignment within its scope outright, while a `SOFT` conflict bars only the `CHAIR` role. Filing a declaration is an OCC-guarded write requiring `expected_judge_version` (§2.9), and it advances the judge's `version`. Declarations are born `DECLARED`; a `ProgramAdmin` acknowledges them, producing `ACKNOWLEDGED`; and the declaring judge — or a `ProgramAdmin` as override — may rescind one still in `DECLARED`, producing the terminal `RESCINDED`. Rescinding the only `HARD` conflict blocking a `PROPOSED` assignment unblocks that assignment's confirmation. Declarations can be listed per judge (filters `season_id`, `status`), per season (filters `judge_id`, `entrant_id`), per entrant (filter `season_id`), or per category.

Panels are assembled round by round. A `ProgramAdmin` proposes an assignment of a judge to a scoring round with a `role` of `CHAIR` or `MEMBER`; the round must still be `CONFIGURING`, and the write requires `expected_scoring_round_version` because proposing an assignment itself advances the round's `version`. The assignment is `PROPOSED` until the named judge confirms it. Confirmation is personal: the acting judge must be the assignee (a mismatch is `ERR_SEGREGATION_OF_DUTIES`), must be `ACTIVE`, and must hold no unresolved `HARD` declaration — one in `DECLARED` or `ACKNOWLEDGED` — that matches either an entrant with an `ELIGIBLE` or `IN_JUDGING` entry in the panel's category or, through a null category scope, the whole season; a violation is `ERR_CONFLICT_OF_INTEREST`. A confirmed assignment becomes `ACTIVE`.

An `ACTIVE` assignment ends in one of three ways. The judge may recuse, moving the assignment to `RECUSED`, which also seeds an `ACKNOWLEDGED` declaration of `HARD` severity and conflict type `OTHER` covering the category if none exists. Program staff may instead remove the assignee (`REMOVED`) while the round is `CONFIGURING` or `PANEL_LOCKED`. Both recusal and removal void every `DRAFT` score the judge holds in that round, recompute the judge's reliability, and demote the round from `PANEL_LOCKED` back to `CONFIGURING` if active membership has fallen below `panel_size`. Third, when the round is normalized, the surviving `ACTIVE` assignments complete (`COMPLETED`) and reliability is recomputed once more. Reliability is the share of decided assignments — those `COMPLETED`, `REMOVED`, or `RECUSED` — that were completed, expressed in basis points: a judge with no decided assignments keeps 10,000; otherwise the value is the completed count divided by the decided count, multiplied by 10,000, and rounded half-up to a whole number.

### 3.6. Scoring Rounds, Ballots, and Normalization

Each category is scored in up to three rounds, created by a `ProgramAdmin` with a `round_index` of 1, 2, or 3 — the round's `name` derives from the index as `SCREENING`, `SEMIFINAL`, or `FINAL` respectively — an `advance_count` saying how many top entries advance from a non-final round (the `FINAL` round uses the category's `finalist_slots` instead), a `scoring_mode` of `RAW_RANK` or `Z_SCORE`, and a planned window from `scheduled_window_start` to `scheduled_window_end`, the end strictly after the start. Within a category, at most one non-`VOIDED` round may exist per `round_index` — a `VOIDED` round may be superseded by a replacement carrying the same index — and any two non-`VOIDED` rounds' windows must be separated by a closed buffer of at least twelve hours: the gap between the earlier window's end and the later window's start must be twelve hours or more, mere non-overlap being insufficient, and a violation is `ERR_ROUND_WINDOW_TOO_CLOSE`. A new round is `CONFIGURING`; rounds can be listed with a `status` filter.

Locking the panel moves a round from `CONFIGURING` to `PANEL_LOCKED` and requires the season to be `SUBMISSION_CLOSED` or `JUDGING`, at least `panel_size` `ACTIVE` assignments, and exactly one `ACTIVE` assignment in the `CHAIR` role; a shortfall is `ERR_PANEL_INCOMPLETE`, and a duplicated chair is rejected as `ERR_CONSTRAINT_VIOLATION`. The lock appends `ROUND_PANEL_LOCKED`. Opening the round requires the season to be `JUDGING`, requires this round's index to be the smallest among the category's non-`VOIDED` rounds that have not yet reached `NORMALIZED`, requires the non-`VOIDED` round with the immediately preceding index — if one exists — to be `NORMALIZED` already (rounds always run in ascending index order), and requires a non-empty candidate set: for the lowest-indexed round, every `IN_JUDGING` entry in the category; for later rounds, the entries that advanced from the immediately preceding round. Opening stamps `opened_at` and appends `ROUND_OPEN`.

While a round is `OPEN`, each panelist drafts a ballot for a candidate entry with a payload carrying the `entry_id`, their own `judge_id`, a `criterion_scores` map, and `expected_scoring_round_version`. The acting judge must hold an `ACTIVE` assignment in the round and the entry must be a candidate of it — otherwise the create is `ERR_REFERENTIAL_INTEGRITY` — and a judge is barred from scoring any entry whose entrant they conflict with — the conflict bar is enforced both when the ballot is created and when it is submitted, and either attempt is refused with `ERR_CONFLICT_OF_INTEREST`. Ballot creation advances the round's `version`, so a panelist re-reads the round before each guarded write. Scores are evidence records carrying only `id` and `created_at`, born `DRAFT` with their computed fields unset. Submitting a ballot — again personal to the scoring judge, and only while the round is `OPEN` — requires every rubric criterion to be present in `criterion_scores` with a value between zero and that criterion's `max_score` inclusive; gaps or out-of-range values are `ERR_CONSTRAINT_VIOLATION`. At submission the weighted raw composite is computed and stored as `weighted_raw`: for each criterion, the raw score is divided by the criterion's `max_score`, multiplied by the criterion's `weight_bp`, and divided by 100, and each such contribution is rounded half-up to four decimal places before any summation; `weighted_raw` is then the sum of those rounded contributions, itself rounded half-up to four decimal places, yielding a value between 0 and 100. The ballot is then `SUBMITTED`. Scores can be listed per round (filters `judge_id`, `entry_id`, `status`), per entry (filter `scoring_round_id`), or per judge (filter `scoring_round_id`).

Closing the round is allowed only on a complete ballot: every `ACTIVE` panelist must hold a `SUBMITTED` or `LOCKED` score for every candidate entry, otherwise the close is refused with `ERR_INCOMPLETE_BALLOT`. Closing stamps `closed_at`, locks every `SUBMITTED` score (and `LOCKED` is terminal for a score), and appends `ROUND_CLOSE`.

Normalization converts locked ballots into comparable standings, computed over exactly the `LOCKED` scores whose judges were `ACTIVE` at close. The two scoring modes diverge deliberately, so identical raw inputs yield different normalized values under each. Under `Z_SCORE`, the system computes each judge's mean and population standard deviation across that judge's `weighted_raw` values, writes each score's `z_intermediate` as its deviation from its judge's mean divided by its judge's standard deviation — zero when that standard deviation is zero — and then rescales across the whole round: the minimum and maximum `z_intermediate` over all scores define the range, and each `normalized_score` is its distance above the minimum, divided by that range, multiplied by 100, rounded half-up to four decimal places; if the maximum equals the minimum, every score normalizes to exactly 50. Under `RAW_RANK`, with N the count of distinct candidate entries in the round, each judge's locked scores are ranked by `weighted_raw` descending with ties sharing the average rank, the rank is stored as `rank_among_judges_scores`, and each `normalized_score` is N minus that rank, divided by N minus one, multiplied by 100, rounded half-up to four decimal places; a single-candidate round normalizes to 100. The intermediate fields are mode-exclusive: `z_intermediate` stays null under `RAW_RANK`, and `rank_among_judges_scores` stays null under `Z_SCORE`; `normalized_score` is null until the round is normalized. An entry's composite for the round is the mean of its `normalized_score` values across the panel, rounded half-up to four decimal places.

Normalization also freezes the round's `normalization_snapshot` — per-judge mean, standard deviation, count, minimum, and maximum — which later drives deterministic recomputation on appeal. For `SCREENING` and `SEMIFINAL` rounds, the top `advance_count` entries by composite are marked as advancing. For the `FINAL` round, normalization writes each candidate's `final_composite_score` and `final_rank`. The final composite blends the entry's per-round composites with base weights of 0.20 for `SCREENING`, 0.30 for `SEMIFINAL`, and 0.50 for `FINAL`; when a category ran fewer than three rounds, the missing rounds' weights redistribute proportionally, each present non-`VOIDED` round's effective weight being its base weight divided by the sum of the base weights of the present rounds — a `FINAL`-only category therefore gives the `FINAL` round an effective weight of 1.0, and a category that ran only `SCREENING` and `FINAL` uses 0.20 divided by 0.70 and 0.50 divided by 0.70. The entry's `final_composite_score` is the sum over present rounds of each effective weight multiplied by the entry's composite in that round, rounded half-up to four decimal places, and `final_rank` orders entries by that composite descending, breaking ties by the `FINAL`-round composite descending and then by entry `created_at` ascending. Normalization completes every still-`ACTIVE` assignment (`COMPLETED`), appends `ROUND_NORMALIZED`, and moves the round to `NORMALIZED`.

### 3.7. Finalists, Embargo, Ceremony, and Winner Announcements

Once every `PUBLISHED` category's `FINAL` round stands `NORMALIZED`, a `ProgramAdmin` locks the finalists, moving the season from `JUDGING` to `FINALISTS_LOCKED`. For each `PUBLISHED` category the system creates one finalist record per top entry, taking the category's `finalist_slots` highest entries by `final_composite_score` — ties broken by the entry's `FINAL`-round `weighted_raw` descending, then by the entry's `created_at` ascending — and freezing each record's `announced_rank` as a snapshot of the rank at announcement time. The selected entries become `FINALIST`; every other `IN_JUDGING` entry in the category becomes `NON_FINALIST`, and no fulfillment order is created for them at this point, since certificates are issued only at announcement time. The `FINAL` rounds themselves cascade from `NORMALIZED` to `PUBLISHED` in the same step, and the transition appends `SEASON_LOCK_FINALISTS`. Each finalist record is born with `notification_status` `PENDING`, `notified_at` unset, and `embargo_visible` false; records can be listed per category with a `notification_status` filter, and a single entry's finalist record (an array of zero or one) can be read directly.

Notification then proceeds record by record while the season is `FINALISTS_LOCKED` or `EMBARGOED`: a `ProgramAdmin` notifies a `PENDING` record, moving it to `NOTIFIED` and stamping `notified_at`. The entrant that owns the underlying entry acknowledges within `ack_window_hours` of `notified_at` — acknowledgement after that window is refused with `ERR_OUTSIDE_WINDOW` — moving the record to `ACKNOWLEDGED`. The entrant may instead decline, and the clock sweep auto-declines any `NOTIFIED` record whose acknowledgement window lapses; either path produces `DECLINED`, which is terminal, and triggers finalist promotion: the highest-ranked `NON_FINALIST` entry in the category, ordered by `final_composite_score` descending, then `FINAL`-round composite descending, then `created_at` ascending, is promoted to `FINALIST` with a fresh record in `PENDING` whose `announced_rank` inherits the vacated rank, while the declining entry's status becomes `NON_FINALIST`; if no candidate remains, the slot simply stays vacant. Separately, an `ACKNOWLEDGED` record is revoked — terminal `REVOKED` — when an appeal-driven recomputation pushes the entry's `final_rank` beyond `finalist_slots`; revocation returns the entry to `NON_FINALIST` and cancels any linked `CERTIFICATE` fulfillment order still in `DRAFT` or `QUEUED`.

With every record resolved to `NOTIFIED`, `ACKNOWLEDGED`, or `DECLINED`, and with `ceremony_scheduled_at` set to a future instant, the `ProgramAdmin` places the season under embargo by supplying an `embargo_lifts_at` that must lie strictly after the current clock. The season becomes `EMBARGOED`, the argument is stored on the season, and `SEASON_EMBARGO` is appended. Note the ordering implication: notification can continue under embargo, but every record must first be out of `PENDING`.

Ceremony production proceeds in parallel. A `ProgramAdmin` creates a ceremony for the season with a `venue_name`, a `starts_at` that must equal the season's `ceremony_scheduled_at`, an `ends_at` strictly after the start, and a `rundown` — an ordered list of segments, each with a `segment_no`, a `category_id`, and a `duration_seconds`, where `segment_no` values are unique and contiguous from 1. Within one season, the half-open intervals from `starts_at` to `ends_at` of non-terminal ceremonies must never overlap; two ceremonies that merely touch — one ending exactly when the other begins — are permitted, and an overlap is rejected with `ERR_CEREMONY_OVERLAP`. A ceremony begins in `PLANNING` and advances to `REHEARSAL` only while the season is `EMBARGOED` and only when its rundown covers every `PUBLISHED` category exactly once — a rundown with a gap, a duplicate, or non-contiguous numbering is rejected with `ERR_CONSTRAINT_VIOLATION` (and a duplicate `segment_no` at creation is `ERR_DUPLICATE`); a rehearsal may be abandoned, and aborting from `PLANNING` or `REHEARSAL` produces the terminal `ABORTED`. Ceremonies list with a `status` filter.

Going live is the hinge of the whole program. It requires the season to be `EMBARGOED`, selects the season's single `REHEARSAL` ceremony — if several qualify, the one with the earliest `starts_at`, ties broken by `created_at` ascending — and requires the clock to have reached the ceremony's start minus the season's `go_live_lead_minutes`; an early attempt is `ERR_OUTSIDE_WINDOW`. The season becomes `CEREMONY_LIVE`, the selected ceremony becomes `LIVE`, every finalist record's `embargo_visible` is set to true if the clock has already passed `embargo_lifts_at`, and `SEASON_GO_LIVE` is appended.

Winner announcements are staged ahead of time: a `ProgramAdmin` stages an announcement for a category with a payload containing the `ceremony_id`, producing a `STAGED` announcement whose `winner_entry_id` is not yet computed. Announcing requires the announcement to be `STAGED` or `RESTAGED`, the season `CEREMONY_LIVE`, the ceremony `LIVE`, and the clock at or past `embargo_lifts_at`. The announce step resolves `winner_entry_id` to the entry holding `final_rank` 1 in the category — an announcement without a rank-1 holder is `ERR_REFERENTIAL_INTEGRITY`, as is notifying a finalist record for an entry that is not `FINALIST` — stamps `announced_at`, moves the announcement to `ANNOUNCED`, and fans out: the winning entry becomes `WINNER`, every other `FINALIST` entry in the category becomes `NON_WINNER`, a `TROPHY` fulfillment order is created for the winner, a `CERTIFICATE` fulfillment order is created for each non-winning finalist, and `WINNER_ANNOUNCED` is appended. Concluding the ceremony — `LIVE` to `CONCLUDED` — requires every `PUBLISHED` category to hold an `ANNOUNCED` announcement. With all categories announced and the ceremony concluded, publishing results moves the season to `PUBLISHED`, sets `embargo_visible` true on every finalist record, and appends `SEASON_PUBLISH`.

### 3.8. Appeals, Remediation, Fulfillment, and Archival

Any entrant with competitor standing may appeal a result by filing an appeal against an entry with a payload carrying `filed_by_entrant_id`, `grounds` — one of `SCORING_ERROR`, `CONFLICT_UNDECLARED`, `ELIGIBILITY_MISREAD`, or `PROCEDURAL_VIOLATION` — and a free-text `narrative`. The `filed_by_entrant_id` must match the acting user's own `Entrant` `id`, and the filing entrant must own at least one non-`WITHDRAWN` entry in the appealed entry's category. An entry may carry fewer than the season's `max_appeals_per_entry` appeals in the non-terminal states `FILED` and `UNDER_REVIEW`; a filing at the cap is rejected with `ERR_APPEAL_CAP_EXCEEDED`. New appeals are `FILED`, and appeals can be listed per entry or per filing entrant, each with a `status` filter.

An `Auditor` takes an appeal under review (`FILED` to `UNDER_REVIEW`), and segregation of duties is enforced at every decision point: the acting auditor's identity must differ from the filing entrant's owning user id, so the same person may never both file and decide (`ERR_SEGREGATION_OF_DUTIES`). Taking an appeal under review moves the season's `integrity_flag` to `UNDER_REVIEW`. The auditor then decides. Denial records `decided_at` and moves the appeal to `DENIED`; if no other appeal in the season remains in `FILED` or `UNDER_REVIEW`, the season's `integrity_flag` returns to `CLEAN`. Upholding requires a `remedy` argument of `RESCORE`, `REINSTATE`, or `NONE`; it records `decided_at`, records the acting auditor's opaque id in `decided_by`, stores the `remedy`, and appends `APPEAL_UPHELD`. A `RESCORE` remedy voids the scoring round that produced the appealed score — `NORMALIZED` to `VOIDED` — and, when the grounds are `CONFLICT_UNDECLARED`, also voids every `LOCKED` score cast by the conflicted judge in that round; a replacement round with the same `round_index` may then be created, since the voided round no longer blocks uniqueness, and its normalization must reuse the voided round's frozen `normalization_snapshot` for every judge whose scores remain `LOCKED`. A `REINSTATE` remedy against an `INELIGIBLE` entry returns it to `UNDER_REVIEW` with `payment_status` restored to `PAID`. The filing entrant may withdraw a still-`FILED` appeal, producing `WITHDRAWN`.

When an upheld `RESCORE` appeal targets an entry that was announced as winner, the retraction path opens. An `Auditor` retracts the announcement, recording a `retraction_reason`; the announcement moves from `ANNOUNCED` to `RETRACTED`, the season's `integrity_flag` becomes `UNDER_REVIEW`, and `WINNER_RETRACTED` is appended. The winner's disposition depends on the grounds: with `CONFLICT_UNDECLARED` the entry is disqualified outright — `disqualified_reason` is recorded, the entrant's `lifetime_disqualifications` is incremented by one (reaching three promotes the entrant to `BARRED`), the season's `active_entries_count` is decremented by one, and any linked fulfillment order not yet `SHIPPED` or `DELIVERED` is cancelled — while under any other grounds the entry stays `FINALIST` pending the rescore. Retraction also cancels the winner's `TROPHY` order while it is still in `DRAFT`, `QUEUED`, or `IN_PRODUCTION`. Once the replacement `FINAL` round reaches `NORMALIZED`, a `ProgramAdmin` restages the retracted announcement, which recomputes `winner_entry_id` from the replacement round and moves the announcement to `RESTAGED`, from which it can be announced again under the usual announce preconditions. Announcements can be listed per category (filter `status`) or per ceremony, and the announcements naming a given entry as winner can be listed from the entry.

Fulfillment orders are created by the announcement cascade — one `TROPHY` order for the rank-1 winner and one `CERTIFICATE` order per non-winning finalist — each bound to its `season_id`, `entry_id`, and `announcement_id`, with `item_type` `TROPHY` or `CERTIFICATE`, an `engraving_text`, and a `quantity` of at least one (default 1). Orders are born `DRAFT`, and `engraving_text` is immutable once the order leaves `DRAFT`. A `FulfillmentVendor` queues a `DRAFT` order — permitted only while the linked announcement is `ANNOUNCED` and the season is `CEREMONY_LIVE` or `PUBLISHED` — optionally supplying or correcting `engraving_text` and `quantity` at queue time; queuing assigns the `vendor_reference` and moves the order to `QUEUED`. The vendor then walks the production pipeline: starting production (`IN_PRODUCTION`), shipping (`SHIPPED`), and delivery (`DELIVERED`, terminal). Beyond the retraction and revocation cascades already described, the system cancels an order in `DRAFT`, `QUEUED`, or `IN_PRODUCTION` whenever winner retraction, finalist revocation, or entry disqualification voids its basis; `CANCELLED` is terminal. Orders can be listed per season (filters `status`, `item_type`), per entry (filter `status`), or per announcement.

Archival closes the season. A `ProgramAdmin` archives a `PUBLISHED` season only when no appeal in `FILED` or `UNDER_REVIEW` remains against any entry in the season and every fulfillment order for the season stands in `DELIVERED` or `CANCELLED`; the season becomes `ARCHIVED` — terminal, like `CANCELLED` — and `SEASON_ARCHIVE` is appended. Throughout the lifecycle, every state change on an entity already in a terminal state is refused with `ERR_ALREADY_TERMINAL`, and any action whose source state does not permit the transition is refused with `ERR_INVALID_STATE`. Program staff and auditors can read the season's audit log at any point; the hash-chain verification described in §2.11 runs on every such read.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection — seasons, categories, entrants, entries, materials, judges, conflict declarations, scoring rounds, panel assignments, scores, ceremonies, announcements, and appeals — return `201 Created`. Operations that modify or transition an existing resource, including the clock-setting capability, return `200 OK`. The complete request and response shape of every operation is defined by the §3 narratives; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/awards/_clock/set_current_utc` | Set the logical server clock (test-driving); runs the clock sweep | ProgramAdmin |
| POST | `/awards/seasons` | Create a season in `DRAFT` | ProgramAdmin |
| GET | `/awards/seasons` | List seasons | ProgramAdmin, Auditor, Entrant, Judge, FulfillmentVendor, Anonymous |
| GET | `/awards/seasons/{id}` | Get season by id | ProgramAdmin, Auditor, Entrant, Judge, FulfillmentVendor, Anonymous |
| POST | `/awards/seasons/{id}/open` | Open a season (`DRAFT` → `OPEN`) | ProgramAdmin |
| POST | `/awards/seasons/{id}/close-submissions` | Close submissions (`OPEN` → `SUBMISSION_CLOSED`); sweeps late drafts | ProgramAdmin |
| POST | `/awards/seasons/{id}/begin-judging` | Begin judging (`SUBMISSION_CLOSED` → `JUDGING`) | ProgramAdmin |
| POST | `/awards/seasons/{id}/lock-finalists` | Lock finalists (`JUDGING` → `FINALISTS_LOCKED`); creates finalist records | ProgramAdmin |
| POST | `/awards/seasons/{id}/embargo` | Embargo results (`FINALISTS_LOCKED` → `EMBARGOED`) with `embargo_lifts_at` | ProgramAdmin |
| POST | `/awards/seasons/{id}/go-live` | Go live (`EMBARGOED` → `CEREMONY_LIVE`) | ProgramAdmin |
| POST | `/awards/seasons/{id}/publish-results` | Publish results (`CEREMONY_LIVE` → `PUBLISHED`) | ProgramAdmin |
| POST | `/awards/seasons/{id}/archive` | Archive season (`PUBLISHED` → `ARCHIVED`) | ProgramAdmin |
| POST | `/awards/seasons/{id}/cancel` | Cancel season (`DRAFT`/`OPEN` → `CANCELLED`) | ProgramAdmin |
| POST | `/awards/seasons/{id}/categories` | Create category under season | ProgramAdmin |
| GET | `/awards/seasons/{id}/categories` | List categories of a season | ProgramAdmin, Auditor, Entrant, Judge, FulfillmentVendor, Anonymous |
| GET | `/awards/categories/{id}` | Get category | ProgramAdmin, Auditor, Entrant, Judge, FulfillmentVendor, Anonymous |
| POST | `/awards/categories/{id}/publish` | Publish category (`DRAFT`/`SUSPENDED` → `PUBLISHED`) | ProgramAdmin |
| POST | `/awards/categories/{id}/suspend` | Suspend category (`PUBLISHED` → `SUSPENDED`) | ProgramAdmin |
| POST | `/awards/categories/{id}/retire` | Retire category (`PUBLISHED` → `RETIRED`) | ProgramAdmin |
| POST | `/awards/entrants` | Register entrant | ProgramAdmin |
| GET | `/awards/entrants` | List entrants | ProgramAdmin, Auditor |
| GET | `/awards/entrants/{id}` | Get entrant | ProgramAdmin, Auditor, Entrant |
| GET | `/awards/entrants/{id}/entries` | List entries owned by entrant | ProgramAdmin, Auditor, Entrant |
| POST | `/awards/categories/{id}/entries` | Create entry in `DRAFT` | Entrant |
| GET | `/awards/categories/{id}/entries` | List entries in category | ProgramAdmin, Auditor |
| GET | `/awards/entries/{id}` | Get entry; result fields nulled for `Anonymous` until embargo lifts | ProgramAdmin, Auditor, Entrant, Judge, Anonymous |
| POST | `/awards/entries/{id}/materials` | Attach material to entry | Entrant |
| GET | `/awards/entries/{id}/materials` | List materials of entry | ProgramAdmin, Auditor, Entrant |
| POST | `/awards/materials/{id}/accept` | Accept material (`PENDING` → `ACCEPTED`) | ProgramAdmin |
| POST | `/awards/materials/{id}/reject` | Reject material (`PENDING` → `REJECTED`) | ProgramAdmin |
| POST | `/awards/entries/{id}/submit` | Submit entry (`DRAFT` → `SUBMITTED`); creates fee invoice | Entrant |
| POST | `/awards/entries/{id}/waive-fee` | Grant fee waiver while entry is `DRAFT` | ProgramAdmin |
| POST | `/awards/entries/{id}/mark-eligible` | Mark entry eligible (`UNDER_REVIEW` → `ELIGIBLE`) | ProgramAdmin |
| POST | `/awards/entries/{id}/mark-ineligible` | Mark entry ineligible (`UNDER_REVIEW` → `INELIGIBLE`) | ProgramAdmin |
| POST | `/awards/entries/{id}/request-recheck` | Request recheck (`INELIGIBLE` → `UNDER_REVIEW`) | Entrant |
| POST | `/awards/entries/{id}/withdraw` | Withdraw entry (`DRAFT`/`SUBMITTED`/`UNDER_REVIEW` → `WITHDRAWN`) | Entrant |
| GET | `/awards/entries/{id}/invoices` | List invoices for entry | ProgramAdmin, Auditor, Entrant |
| GET | `/awards/invoices/{id}` | Get invoice | ProgramAdmin, Auditor, Entrant |
| POST | `/awards/invoices/{id}/pay` | Pay invoice (`ISSUED` → `PAID`) | Entrant |
| POST | `/awards/judges` | Invite judge (creates `INVITED`) | ProgramAdmin |
| GET | `/awards/judges` | List judges | ProgramAdmin, Auditor |
| GET | `/awards/judges/{id}` | Get judge | ProgramAdmin, Auditor, Judge |
| POST | `/awards/judges/{id}/accept` | Accept invitation (`INVITED` → `ACCEPTED`); seeds conflict declarations | Judge |
| POST | `/awards/judges/{id}/decline` | Decline invitation (`INVITED` → `DECLINED`) | Judge |
| POST | `/awards/judges/{id}/activate` | Activate judge (`ACCEPTED`/`SUSPENDED` → `ACTIVE`) | ProgramAdmin |
| POST | `/awards/judges/{id}/suspend` | Suspend judge (`ACTIVE` → `SUSPENDED`); removes panel assignments | ProgramAdmin |
| POST | `/awards/judges/{id}/retire` | Retire judge (`ACTIVE`/`SUSPENDED` → `RETIRED`) | ProgramAdmin |
| POST | `/awards/judges/{id}/conflict-declarations` | File conflict declaration (OCC on judge version) | Judge, ProgramAdmin |
| GET | `/awards/judges/{id}/conflict-declarations` | List declarations by judge | ProgramAdmin, Auditor, Judge |
| GET | `/awards/seasons/{id}/conflict-declarations` | List declarations by season | ProgramAdmin, Auditor |
| GET | `/awards/entrants/{id}/conflict-declarations` | List declarations against an entrant | ProgramAdmin, Auditor |
| GET | `/awards/categories/{id}/conflict-declarations` | List declarations scoped to a category | ProgramAdmin, Auditor |
| POST | `/awards/conflict-declarations/{id}/acknowledge` | Acknowledge declaration (`DECLARED` → `ACKNOWLEDGED`) | ProgramAdmin |
| POST | `/awards/conflict-declarations/{id}/rescind` | Rescind declaration (`DECLARED` → `RESCINDED`) | Judge, ProgramAdmin |
| POST | `/awards/categories/{id}/scoring-rounds` | Create scoring round | ProgramAdmin |
| GET | `/awards/categories/{id}/scoring-rounds` | List rounds of category | ProgramAdmin, Auditor, Judge |
| GET | `/awards/scoring-rounds/{id}` | Get round | ProgramAdmin, Auditor, Judge |
| POST | `/awards/scoring-rounds/{id}/panel-assignments` | Propose panel assignment (OCC on round version) | ProgramAdmin |
| GET | `/awards/scoring-rounds/{id}/panel-assignments` | List assignments of round | ProgramAdmin, Auditor, Judge |
| GET | `/awards/judges/{id}/panel-assignments` | List assignments of judge | ProgramAdmin, Auditor, Judge |
| GET | `/awards/categories/{id}/panel-assignments` | List assignments by category | ProgramAdmin, Auditor |
| POST | `/awards/panel-assignments/{id}/confirm` | Confirm assignment (`PROPOSED` → `ACTIVE`) | Judge |
| POST | `/awards/panel-assignments/{id}/recuse` | Recuse from assignment (`ACTIVE` → `RECUSED`) | Judge |
| POST | `/awards/panel-assignments/{id}/remove` | Remove assignment (`ACTIVE` → `REMOVED`) | ProgramAdmin |
| POST | `/awards/scoring-rounds/{id}/lock-panel` | Lock panel (`CONFIGURING` → `PANEL_LOCKED`) | ProgramAdmin |
| POST | `/awards/scoring-rounds/{id}/open` | Open round (`PANEL_LOCKED` → `OPEN`) | ProgramAdmin |
| POST | `/awards/scoring-rounds/{id}/close` | Close round (`OPEN` → `CLOSED`); locks submitted scores | ProgramAdmin |
| POST | `/awards/scoring-rounds/{id}/normalize` | Normalize round (`CLOSED` → `NORMALIZED`) | ProgramAdmin |
| POST | `/awards/scoring-rounds/{id}/scores` | Create `DRAFT` score (OCC on round version) | Judge |
| GET | `/awards/scoring-rounds/{id}/scores` | List scores of round | ProgramAdmin, Auditor, Judge |
| GET | `/awards/entries/{id}/scores` | List scores of entry | ProgramAdmin, Auditor, Entrant |
| GET | `/awards/judges/{id}/scores` | List scores by judge | ProgramAdmin, Auditor, Judge |
| POST | `/awards/scores/{id}/submit` | Submit score (`DRAFT` → `SUBMITTED`) | Judge |
| GET | `/awards/categories/{id}/finalists` | List finalist records of category; `Anonymous` sees only embargo-visible records | ProgramAdmin, Auditor, Entrant, Judge, Anonymous |
| GET | `/awards/entries/{id}/finalist-record` | Get finalist record for entry (array of 0..1) | ProgramAdmin, Auditor, Entrant |
| GET | `/awards/entries/{id}/announcements` | List announcements whose winner is this entry | ProgramAdmin, Auditor |
| POST | `/awards/finalists/{id}/notify` | Notify finalist (`PENDING` → `NOTIFIED`) | ProgramAdmin |
| POST | `/awards/finalists/{id}/acknowledge` | Acknowledge notification (`NOTIFIED` → `ACKNOWLEDGED`) | Entrant |
| POST | `/awards/finalists/{id}/decline` | Decline notification (`NOTIFIED` → `DECLINED`); promotes next entry | Entrant |
| POST | `/awards/seasons/{id}/ceremonies` | Create ceremony | ProgramAdmin |
| GET | `/awards/seasons/{id}/ceremonies` | List ceremonies of season | ProgramAdmin, Auditor, Entrant, Judge, Anonymous |
| GET | `/awards/ceremonies/{id}` | Get ceremony by id | ProgramAdmin, Auditor, Entrant, Judge, Anonymous |
| POST | `/awards/ceremonies/{id}/rehearse` | Move ceremony to rehearsal (`PLANNING` → `REHEARSAL`) | ProgramAdmin |
| POST | `/awards/ceremonies/{id}/conclude` | Conclude ceremony (`LIVE` → `CONCLUDED`) | ProgramAdmin |
| POST | `/awards/ceremonies/{id}/abort` | Abort ceremony (`PLANNING`/`REHEARSAL` → `ABORTED`) | ProgramAdmin |
| POST | `/awards/categories/{id}/announcements` | Stage winner announcement for a category at a ceremony | ProgramAdmin |
| GET | `/awards/announcements/{id}` | Get announcement by id | ProgramAdmin, Auditor, Anonymous |
| GET | `/awards/categories/{id}/announcements` | List announcements of category | ProgramAdmin, Auditor, Anonymous |
| GET | `/awards/ceremonies/{id}/announcements` | List announcements at ceremony | ProgramAdmin, Auditor, Anonymous |
| POST | `/awards/announcements/{id}/announce` | Announce winner (`STAGED`/`RESTAGED` → `ANNOUNCED`); cascades entries and fulfillment | ProgramAdmin |
| POST | `/awards/announcements/{id}/retract` | Retract announcement (`ANNOUNCED` → `RETRACTED`) on upheld appeal | Auditor |
| POST | `/awards/announcements/{id}/restage` | Restage announcement (`RETRACTED` → `RESTAGED`) after replacement round normalizes | ProgramAdmin |
| GET | `/awards/seasons/{id}/fulfillment-orders` | List fulfillment orders of season | ProgramAdmin, FulfillmentVendor |
| GET | `/awards/entries/{id}/fulfillment-orders` | List fulfillment orders of entry | ProgramAdmin, Entrant, FulfillmentVendor |
| GET | `/awards/announcements/{id}/fulfillment-orders` | List orders authorized by announcement | ProgramAdmin, FulfillmentVendor |
| POST | `/awards/fulfillment-orders/{id}/queue` | Queue order (`DRAFT` → `QUEUED`); assigns vendor reference | FulfillmentVendor |
| POST | `/awards/fulfillment-orders/{id}/start-production` | Start production (`QUEUED` → `IN_PRODUCTION`) | FulfillmentVendor |
| POST | `/awards/fulfillment-orders/{id}/ship` | Ship order (`IN_PRODUCTION` → `SHIPPED`) | FulfillmentVendor |
| POST | `/awards/fulfillment-orders/{id}/deliver` | Mark delivered (`SHIPPED` → `DELIVERED`) | FulfillmentVendor |
| POST | `/awards/entries/{id}/appeals` | File appeal | Entrant |
| GET | `/awards/entries/{id}/appeals` | List appeals of entry | ProgramAdmin, Auditor, Entrant |
| GET | `/awards/entrants/{id}/appeals` | List appeals filed by entrant | ProgramAdmin, Auditor, Entrant |
| POST | `/awards/appeals/{id}/take-under-review` | Take appeal under review (`FILED` → `UNDER_REVIEW`) | Auditor |
| POST | `/awards/appeals/{id}/uphold` | Uphold appeal with remedy (`UNDER_REVIEW` → `UPHELD`) | Auditor |
| POST | `/awards/appeals/{id}/deny` | Deny appeal (`UNDER_REVIEW` → `DENIED`) | Auditor |
| POST | `/awards/appeals/{id}/withdraw` | Withdraw appeal (`FILED` → `WITHDRAWN`) | Entrant |
| GET | `/awards/seasons/{id}/audit-logs` | List audit log rows of season; verifies hash chain on read | ProgramAdmin, Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives; this table fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_ELIGIBILITY_WINDOW` | 422 Unprocessable Entity |
| `ERR_CEREMONY_OVERLAP` | 422 Unprocessable Entity |
| `ERR_ROUND_WINDOW_TOO_CLOSE` | 422 Unprocessable Entity |
| `ERR_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_CONSTRAINT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_FISCAL_BLOCK` | 402 Payment Required |
| `ERR_PANEL_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_INCOMPLETE_BALLOT` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_APPEAL_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EMBARGO_ACTIVE` | 403 Forbidden |
| `ERR_HASH_CHAIN_BROKEN` | 409 Conflict |
