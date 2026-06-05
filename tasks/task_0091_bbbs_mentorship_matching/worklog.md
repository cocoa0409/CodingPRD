# Worklog — task_0091_bbbs_mentorship_matching

## Step 1: Create task directory — 2026-06-01T13:05:11.000Z

Created `tasks/task_0091_bbbs_mentorship_matching/` and `tasks/task_0091_bbbs_mentorship_matching/workspace/` (pre-assigned directory; Step 1 auto-index scan skipped per orchestrator instructions).

## Step 2: Generate scaffold (EXPERT difficulty) — 2026-06-01T13:36:49.000Z

All three required files are in place and lint-clean. The scaffold was generated purely from the scenario description and the skill specification — no sibling task was consulted.

**Task 0091 — Big Brothers Big Sisters One-on-One Mentorship Matching — EXPERT difficulty scaffold.**

Three files written to `tasks/task_0091_bbbs_mentorship_matching/`: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`. `scaffold_lint.py` verdict: **clean lint** (46 endpoints, 11 entities, 18 §1.8 instances, 28 §1.9 instances, 541 calls scanned; all FK reverse-reachability satisfied).

**Complexity profile:** primary archetype multi-party negotiation + secondary compliance/audit; layers selector_policy, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency; flat topology; parallel state-machine shape; segregation_of_duties role model; immediate consistency.

**Entities (11):** Volunteer, BackgroundCheck, Guardian, Child, MatchProposal, Match (junction), MatchMeeting, ActivityLog (append-only, common_fields:false), SupervisionContact, ExitTransition, OutcomeSurvey.

**State machines (9):** Volunteer (cyclic — re-screen ELIGIBLE→SCREENING loop), BackgroundCheck (PENDING→CLEARED/FLAGGED→EXPIRED), Child (WAITLISTED↔PROPOSED cycle), MatchProposal (OFFERED→ACCEPTED/DECLINED/SUPERSEDED), Match (**parallel axes**: relationship_status × derived compliance_status), MatchMeeting (**branching** HELD→AFFIRMED/RESCINDED), SupervisionContact, ExitTransition (**branching** SUCCESSFUL_CLOSURE vs EARLY_TERMINATION), OutcomeSurvey (append-only). Plus 2 concurrency_rules (OCC on Child.version for propose-supersede, OCC on Volunteer.version for accept-exclusivity).

**Counts:** 5 calculations (2 with variants), 18 validations, 46 endpoints, 19 errors, 4 roles (Coordinator, BackgroundScreener, MatchSpecialist, Supervisor — all opaque).

**Expert-difficulty mechanisms (all 9 §0.5 rules, 2 instances each → 18 total):** dual-variant calcs across two domains (interest score ranking-vs-tiebreak / compliance contact-vs-activity); combinatorial formulas in modes (a) 3-input non-linear interest score and (c) pinned eval-order compliance recompute; non-linear machines on different entities (Match parallel axes / MatchMeeting fork); transitive cascades depth-4 (FLAG→volunteer-fail→proposal-decline→child-waitlist) and depth-3 (finalize→close→volunteer-eligible) from different triggers; priority conflicts across two error-category pairs (state vs safety; referential vs constraint); boundary checks on two metrics/endpoints (30-day strict-> compliance threshold; empty candidate-pool count); cross-entity dependencies on two pairs (Proposal←Volunteer; Child←Guardian); two temporal-overlap rules with different interval semantics on different resources (per-Match half-open / per-Guardian closed+60min buffer); two compensating invariants on different conserved quantities (Volunteer.active_match_count across accept/finalize; Child OFFERED-proposal count across propose/decline). All formula-derived asserts pre-computed to literals (e.g. compatibility_score 0.67/0.80, outcome composite 5.00 STRONG, total minutes 150).

## Step 3: Copy shared files — 2026-06-01T13:37:11.000Z

Copied `INSTRUCTION.md` → `tasks/task_0091_bbbs_mentorship_matching/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-01T13:42:36.000Z

All three Hard Contracts pass. The PRD is complete at `workspace/PRD.md` (~231 lines).

**Section structure:**
- **§1 Introduction** — 2 paragraphs; framed around the two structural invariants (one-on-one exclusivity, segregation of duties) and the dual-axis match health model.
- **§2 Global Specifications** — 8 subsections: 2.1 RBAC (4 roles, all `identity: opaque` translated), 2.2 Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Properties & Versioning (ActivityLog called out as the `common_fields: false` exception — only `id`/`created_at`), 2.5 Optimistic Concurrency, 2.6 Validation Ordering (all 18 priorities in one explicit chain), 2.7 Nested Resource Retrieval, 2.8 Geo/Capacity/Precision conventions.
- **§3 Business Logic** — 7 subsections organized by lifecycle: 3.1 screening, 3.2 validity/expiry/clock, 3.3 enrollment & proposal generation (selector + scoring), 3.4 proposal resolution, 3.5 introduction meeting/activation, 3.6 supervision & activity + compliance derivation, 3.7 exit & outcome survey.
- **§4 Endpoint table** — 4 columns, 46 endpoints, no request/response bodies exposed.
- **§5 Error table** — 2 columns, 19 error IDs.

**Hard Contracts (all PASS):**
- Contract 1 (Field-Name Coverage): 56 entity fields + 4 common + 5 request-body inputs + 8 query params = all present, 0 missing.
- Contract 2 (Rule Coverage): both OCC rules (write op + `expected_<parent>_version` + `ERR_STALE_VERSION`/412), all 5 calculations reconstructible in prose, adverse-tolerance split (CRIMINAL/CHILD_ABUSE_REGISTRY exactly 0 vs DMV at most 1), compliance thresholds (strict >60/>30/>45, MISSED→RED gate), sum-then-round scoring, segregation-of-duties, and the asymmetric closure cascade (NO_SHOW sweep only when closed out of INTRODUCED) all expressed; all 19 error IDs surface in §1–§4 narrative.
- Contract 3 (§3 Path Purity): 315 §3 backtick tokens scanned, 0 path/method/combo leaks — endpoints referenced only via state-transition framing and role+verb modes.

**Notable scattering/ambiguity choices:**
- Endpoint parameters split across ≥2 subsections per guideline — proposal-accept core flow in §3.4 while its OCC `expected_volunteer_version` field lives in §2.5; meeting core fields in §3.5 while geo/precision conventions backing `home_zip` clustering sit in §2.8.
- Numeric constants embedded with unit conversions: VALIDITY_MONTHS as "twenty-four calendar months", CONTACT_INTERVAL_DAYS as "plus thirty days", MEETING_BUFFER_MINUTES as "sixty minutes", CAPACITY_CAP as "capped at 10".
- Dual independent state axes (`relationship_status` × `compliance_status`) kept separated: lifecycle transitions in §3.4–3.7, derived posture algorithm isolated in §3.6 with explicit "if not ACTIVE → GREEN" short-circuit.
- `survey_required`'s "reached ACTIVE at any point" pinning and the EARLY_TERMINATION-vs-SUCCESSFUL_CLOSURE child-fate branch given equal prose density in §3.7.

## Step 5: Generate unit tests — 2026-06-01T14:06:53.000Z

**Helper modules created (Stage 1, `test_helpers/`):** 9 files
- `types.py` — 13 status enums + role enum; entity TypedDicts. `ActivityLog` correctly carries only `id`+`created_at` (append-only, `common_fields: false`); all others carry `updated_at`+`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. `_clock` control).
- `api_errors.py` — `ApiErrorId` enum + HTTP-status map, registered with the framework.
- `assertions.py` — per-entity field/invariant checkers.
- `factories.py` — input-field-only payload factories with unique-email generation.
- `constants.py` — scoring weights, compliance day thresholds, validity months, survey cutoffs, buffer.
- `test_users.py` — shared role-header constants + per-user builders (`make_*_headers(user_id)`); roles are opaque but `X-User-ID` is load-bearing for segregation-of-duties, so builders thread distinct confirm/finalize identities.
- `fixtures.py` — 5-tier composite setup (screening→eligible, propose→accept→confirmed, hold→introduced, affirm→active, exit→closed, survey), threading distinct confirming-specialist vs closing-supervisor IDs to avoid spurious SoD failures.
- `__init__.py` — barrel export.

**Test files (Stage 2, `test_suite/`):** 8 files + `conftest.py`, **60 tests total**.

**Queue breakdown:** Queue-A (Difficulty) = 34 tests across 17 instances (every covered instance has ≥2 tests); Queue-B (Corner) = 26 tests across 26 active instances (≥1 each). All 8 `excluded_because:` stubs verified to cross-reference real difficulty instances; none translated.

**Instances skipped (gaps, no placeholders emitted):**
- **Queue A** `propose_consent_referential_beats_no_eligible_constraint` — PRD does not commit a precedence between the two §3-tier business rules (consent priority 9 vs no-eligible priority 12); §2.6 only orders through priority 6. Not uniquely derivable.
- **Queue B** `complete_contact_when_match_not_active_returns_match_not_active` — unreachable to the asserted `ERR_MATCH_NOT_ACTIVE`: closing the match sweeps the OPEN contact to MISSED (PRD §3.7), so a faithful reader returns `ERR_INVALID_STATE` (state gate, priority 6) first.
- **Queue B** `volunteer_at_capacity_on_second_accept` — `ERR_VOLUNTEER_AT_CAPACITY` unreachable as the *reported* error: PRD never yields a state where `active_match_count≥1` while `status==ELIGIBLE` (they move in lockstep), and the propose-engine excludes matched volunteers, so a faithful reader returns `ERR_VOLUNTEER_NOT_ELIGIBLE` (or `ERR_STALE_VERSION`) first. Confirmed empirically.

**Also dropped (non-derivable assertion within a kept test):** the "back-to-back meeting accepted" half of the per-match overlap test — the per-guardian buffer (§3.5, same guardian) rejects a shared-endpoint meeting with `ERR_GUARDIAN_DOUBLE_BOOKED`, so back-to-back acceptance is not derivable. The overlap-rejection assertion (the rule-bearing one) is retained.

**Validation against the bundled implementation** (initial, pre-Step-7): **59/60 pass.** The single failure (`test_flagged_check_cascades_to_child_waitlist`) flagged as a genuine implementation bug per the test author: the impl's "latest check per type" tie-break uses `created_at >` only, ignoring insertion order — so under the frozen test clock it wrongly treats a stale first-cycle CHILD_ABUSE check as the latest and lets the volunteer go ELIGIBLE instead of SCREENING_FAILED after a re-screen flag (PRD §3.1 mandates SCREENING_FAILED). (To be re-adjudicated in Step 7.)

All audits pass: every test carries exactly one `Design:` tag resolving to a real instance, and every quoted PRD fragment survives a verbatim grep of PRD.md.

## Step 6: Generate implementation — 2026-06-01T14:06:53.000Z

**Task 0091 — BBBS One-on-One Mentorship Matching. Python + Flask, in-memory only, no seeding.**

### Source file structure (19 files in `workspace/implementation/`)
- `start.sh` — guarded-install launcher (`if ! python3 -c "import flask"`), `exec python3 app.py`, reads `$PORT` (default 10000), binds 0.0.0.0.
- `app.py` — Flask app factory, blueprint registration, error handlers (ApiError → standard error envelope; 404/405 → `ERR_NOT_FOUND`; catch-all → 500). No seeding.
- `db.py` — 11 in-memory dicts keyed by id, start empty on every boot.
- `clock.py` — server-controlled clock; follows real UTC until pinned by `/_clock/set_current_utc`.
- `store.py` — record creation with common fields (`id`, `created_at`, `updated_at`, `version` from 1), `touch()` for version/updated_at bump on every mutation (cascades included), a monotonic `_seq` for deterministic ordering, and `paginate`/`sort_key`.
- `errors.py`, `response.py`, `middleware.py`, `validate.py`, `util.py`, `calc.py`, `serialize.py`, `domain.py` — foundation, calculations, serialization, and all bubble-up/cascade logic.
- `routes_clock.py`, `routes_volunteers.py`, `routes_children.py`, `routes_matches.py`, `routes_lifecycle.py` — the route blueprints.

### Endpoints: 46 (exactly matches the PRD §4 endpoint table)

### State machines / calculations organization
- **State machines** in route handlers (preconditions + direct transitions) with all **bubble-ups and cascades centralized in `domain.py`**: `on_check_cleared`/`on_check_flagged`, `close_match` (CLOSED cascade: OPEN contacts→MISSED, SCHEDULED meetings→NO_SHOW only when closed from INTRODUCED, volunteer→ELIGIBLE, child→WAITLISTED/INACTIVE by closure_reason), `revert_child_after_offer_gone`, `sweep_expiry_and_overdue` (clock-advance fired).
- **Derived fields** in `domain.py`: `active_match_count` (non-CLOSED matches), `cleared_check_id`, mentoring-minute/activity/contact rollups. `compliance_status` derived **at read time** in `serialize.match` (GREEN if not ACTIVE; RED if >60 days since contact or any MISSED; AMBER if >30 days contact or >45 days activity; strict `>` boundaries).
- **Calculations** in `calc.py` use `Decimal`/`ROUND_HALF_UP`: compatibility score (sum-then-round-once 0.6·Jaccard + 0.25·geo + 0.15·capacity), outcome composite/band, +24-calendar-month validity, DMV tolerance=1, 60-min meeting buffer.
- OCC: `expected_child_version`/`expected_volunteer_version` → `ERR_STALE_VERSION` (412) before state precondition per §2.6; `expected_guardian_version` required mutation field that also yields 412 on mismatch.

### PRD-ambiguity interpretation choices
1. **Propose-match state precondition.** Read §3.3 to accept `WAITLISTED` **or** `PROPOSED-with-an-open-OFFERED-proposal` (supersede case); `MATCHED`/`INACTIVE` rejected with `ERR_INVALID_STATE`. Superseded prior proposal → SUPERSEDED; child ends PROPOSED on fresh proposal with `version`+1.
2. **Tie-break under frozen clock.** Ties break by earliest `created_at`, "never by id." Added monotonic `_seq` insertion-order counter as deterministic tie-break (and for all list ordering).
3. **active_match_count semantics.** Followed PRD prose (set to 1 on CONFIRMED, 0 on closure) over SCAFFOLD note; one-on-one capacity gate triggers from CONFIRMED onward.
4. **Expiry edge.** Valid while `now < valid_until` (strict); sweep expires when `now >= valid_until`.
5. **Reverse-reachability lists** carry no pagination params → emit all rows (created_at/_seq order) with full `meta`; `/children`, `/volunteers`, `/matches`, `/match-proposals`, `/matches/{id}/activities` honor `limit`/`offset`.

## Step 7: Run tests and iterate — 2026-06-01T14:12:35.000Z

All 8 parallel rounds pass cleanly (60/60 each). Clean sweep achieved.

**Iterations run:** 2 (one diagnostic sweep that surfaced the failure, one confirming sweep after the fix).

**Tests deleted:** None. The single failing test was a genuine implementation bug, not a PRD-silence or unique-derivability problem.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**

- `workspace/implementation/domain.py`, `recompute_volunteer_cleared()` — The "latest check per type wins" selection compared only `created_at` (`c["created_at"] > prev["created_at"]`). Because the test clock is pinned (`REF_CLOCK`), all background checks across re-screening cycles share an identical `created_at`, so the comparison was always False and the *first* (stale, cycle-1) check per type won instead of the freshest. Changed the tie-break to `(created_at, _seq)` so the current re-screen cycle's check is selected. Root cause of the only failing test (`test_flagged_check_cascades_to_child_waitlist`): during a re-screen, clearing the new CRIMINAL check ran `recompute_volunteer_cleared`, which mistakenly saw the *old* cycle-1 checks as still cleared+valid and bumped the volunteer `SCREENING → ELIGIBLE` prematurely. By the time the third (CHILD_ABUSE_REGISTRY) check was FLAGGED, the volunteer was no longer in `SCREENING`, so `on_check_flagged`'s status guard early-returned, leaving it `ELIGIBLE` instead of `SCREENING_FAILED`. This matches PRD §3.1: "A flag arising during a re-screening cycle drives the same `SCREENING_FAILED` outcome."

- `workspace/implementation/domain.py`, `sweep_expiry_and_overdue()` — Preventive hardening (no test was failing on it, but it was the same class of latent pinned-clock flakiness the 8-round sweep is designed to catch). The "newest OPEN contact" selection used `(created_at, id)` as the sort key; under a pinned clock two contacts could tie on `created_at` and be ordered by the random `id` (which the PRD forbids as a tie-break), making which contact gets swept to `MISSED` nondeterministic. Changed to `(created_at, _seq)`.

Storage remains in-memory only; no new endpoints/fields/seed data were introduced. Verified: all 8 results.{1..8}.json report passed=60 total=60.

## Step 8: Finalize PRD — 2026-06-01T14:15:16.000Z

**PRD.md vs PRD_FINALIZED.md**
- Line counts: 231 → 231 (no line added/removed; one paragraph in §3.2 revised in place).
- %-delta: 0% line-count change; 1 of 231 lines modified (~0.43% of lines touched).

**Changes (one bullet per change)**
- §3.2 (Validity, Expiry, and the Test Clock) — revise — Pinned that "the three screens" used for validity/`cleared_check_id` are, for each of the three `check_type`s, the single **most-recently-created** screen of that type (current re-screen cycle supersedes prior cycles of the same type), with recency by creation order and the random `id` never used as the tie-break — `implementation/domain.py:61-91` (`recompute_volunteer_cleared`, the `by_type` latest-per-type selection keyed on `(created_at, _seq)`).

**Per-edit pre-edit search log**

Edit 1 — §3.2 latest-screen-per-type:
- (a) Subject: which screens count as "the three screens" / "all three screens" when re-screening has left multiple cycles of `check_type` records persisted, and how the freshest per type is chosen.
- (b) Enumerated and read impl paths: `domain.py:61-91 recompute_volunteer_cleared` (Step 7 fix site, `by_type` keyed on `(created_at, _seq)`); `domain.py:141-149 on_check_cleared` (SCREENING→ELIGIBLE bubble-up depends on latest-per-type); `domain.py:244-259 sweep_expiry_and_overdue` (re-runs recompute per affected volunteer); `routes_volunteers.py:84-101 submit_screening` (each cycle creates 3 fresh PENDING checks, never deletes old → duplicates coexist); `routes_volunteers.py:140-177 adjudicate_check`; `store.py:17-37,63-66 _seq`/`sort_key` (confirms `_seq` is creation order and `id` never a tie-break). Confirmed no path deletes `background_checks`, so latest-per-type is load-bearing.
- (c) Wording adjustment: Scoped the sentence strictly to *screens* / `check_type` (not supervision contacts or other entities) so it doesn't spill into the §3.6 sweep path; described recency as "creation order / later-created wins" rather than exposing internal `_seq`, and explicitly excluded `id` as a tie-break to match `store.sort_key`/the `by_type` comparison and stay consistent with §3.3's "ties never broken by `id`". No conflict with §3.1's "third screen reaches CLEARED".

**Fix 2 (`sweep_expiry_and_overdue` newest-OPEN-contact tie-break) — no PRD edit.** Step 7 noted no test failed on it (preventive hardening); §3.6 already determines the observable behavior. The `_seq` tie-break only changes behavior when two OPEN contacts share an identical `created_at`, a degenerate case the monthly 30-day cadence does not normally produce; pinning it would add an unwarranted universal claim.

## Step 9: Complete PRD — 2026-06-01T14:20:32.000Z

**Source vs output:**
- `PRD_FINALIZED.md`: 231 lines, 37,728 chars
- `PRD_COMPLETED.md`: 231 lines, 39,173 chars
- Char delta: **+1,445** (line count unchanged; all edits in-paragraph; lines 84, 88, 92, 102, 118, 142, 150 changed)

**Counts:** 3 ambiguity-pins, 4 mismatch-revisions (7 total)

**Per-change:**
- §2.5 (Optimistic Concurrency) — revise — mismatch — PRD claimed "only the two named write operations produce the OCC-specific rejection"; impl rejects a guardian-update version mismatch with `ERR_STALE_VERSION` (and `ERR_INVALID_REQUEST` for a missing/non-int field). Pinned that guardian update does reject. — routes_children.py:51-55
- §2.6 (Validation Ordering) — revise — mismatch — PRD put body-foreign-key existence (`ERR_NOT_FOUND`) in tier 3 ahead of body field validation; impl validates body fields first (tier 4) and checks body-FK existence only afterward, so a malformed field yields `ERR_INVALID_REQUEST` even when a body FK is also missing. — routes_children.py:78-86, routes_lifecycle.py:202-211
- §2.7 (Nested Resource Retrieval) — insert — ambiguity — PRD §2.3 implies all list endpoints honor `limit`/`offset`; impl's nested reverse-reachability reads ignore them and return the full collection with `meta` `limit:10, offset:0, total_count:full`, the sole exception being `GET /matches/{id}/activities`, which paginates. — store.py (hardcoded `10, 0`) routes_children.py:68,219,228,343; routes_matches.py:127,201,210,219; routes_lifecycle.py:167; vs routes_matches.py:162
- §3.1 (Volunteer registration) — revise — mismatch — PRD said volunteer `email` "must be unique among volunteers"; impl never enforces uniqueness. Revised to state email is recorded without a uniqueness check. — routes_volunteers.py:28,36
- §3.1 (Volunteer registration) — insert — ambiguity — PRD §3 prose never described the `/volunteers/{id}/deactivate` transition (only the endpoint table did); impl requires status `ELIGIBLE` and `active_match_count==0`, transitions `ELIGIBLE → INACTIVE`, else `ERR_INVALID_STATE` (409). Pinned. — routes_volunteers.py:105-116
- §3.3 (Guardian registration) — revise — mismatch — PRD said guardian `email` "unique among guardians"; impl never enforces it. Revised to recorded-without-uniqueness-check. — routes_children.py:24-33
- §3.6 (Mentoring activity) — insert — ambiguity — PRD said activities run "once a match is ACTIVE" but never named the rejection for a non-ACTIVE match; impl rejects with `ERR_INVALID_STATE` (409). Pinned. — routes_matches.py:140-141
- §3.7 (Opening an exit) — insert — ambiguity — PRD did not state whether opening a DRAFT exit has a relationship-state precondition; impl applies none (any `relationship_status` allowed at open; the state gate is only at finalize) and computes `survey_required` via `activated_at` non-null. Pinned both (counted as the single §3.7 ambiguity edit). — routes_matches.py:169-192

## Pipeline complete

All 9 steps finished. Final state: 60/60 tests passing across all 8 stability-sweep rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (60 tests), workspace/implementation/ (Flask, in-memory, 46 endpoints).
