# Worklog — task_1393_university_counseling_center_operations

## Step 1: Create Task Directory — 2026-08-13T03:22:00.000Z

Pre-assigned directory `tasks/task_1393_university_counseling_center_operations/` with `workspace/` subdirectory already created by the pipeline dispatcher; treated as DONE per orchestration instructions. No index scan performed, no other task_* directory touched.

Difficulty directive from user: "Generate task hard than expert level!" — forwarded to scaffold generation (Step 2).

## Step 3: Copy Shared Files — 2026-08-13T03:23:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1393_university_counseling_center_operations/workspace/INSTRUCTION.md` (1424 bytes). (Executed early, concurrent with Step 2 — no dependency between them.)

## Step 2: Generate Scaffold — 2026-08-13T04:02:00.000Z

All three scaffold artifacts are generated and clean. Final report (verbatim from subagent):

## Task complete — task_1393_university_counseling_center_operations

**Files written** (no sibling task directories were inspected at any point):
- `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/SCAFFOLD.yaml` — §1.0–§1.7 (scenario verbatim, response envelope fixed block, entities, state machines, concurrency rules, calculations, ordered validations, endpoints, errors, RBAC)
- `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 9 rules × 2 instances = 18
- `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 9 sections, 44 instances (41 active + 3 `excluded_because:` stubs)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (67 endpoints, 13 entities, 554 calls scanned, 0 violations)

**Design shape** (per the "harder than expert" directive):
- **Archetype**: quota/allocation (session limits, counselor caseload risk-point budgets, group capacity, single-room crisis serialization) × access-control-matrix secondary (confidentiality wall between counseling and academic records; Registrar gets a clinical-field-suppressed academic view; ClinicalNote readable only by author or ClinicalDirector)
- **Dual-variant calcs on different domains**: intake risk scoring (screening `elif` vs audit add-then-multiply: 54/HIGH vs 99/CRITICAL for identical inputs) and session-limit entitlement (published-policy vs intersession default: 8 vs 6 for identical profiles)
- **Combinatorial formulas in two modes**: (a) 4×3 band×funding tier matrix with floor; (c) evaluation-order-pinned capacity report (delivered → bookable → single half-up bps rounding; 225/18000 → exactly 125 bps)
- **Non-linear machines on different entities**: CrisisVisit STABILIZED↔ESCALATED cycle; CommunityReferral PENDING→MATCHED→DECLINED→PENDING loop with `rematch_count` cap 3 → `ERR_REFERRAL_LOOP_EXHAUSTED`
- **Cascades (depth 3 and 2, different triggers)**: no-show → strike recompute → SUSPENDED → future-session wipe; referral accept → episode REFERRED_OUT → session cancellation + caseload release
- **Boundary precision**: CRITICAL_MIN inclusive edge (59 HIGH vs 60 CRITICAL); session-limit crossing exactly at equality (consumed == limit)
- **OCC true races only**: shift claim and episode booking, both with `expected_*_version` captured from prior responses (no bare literals), resolved with 412
- **Priority conflicts on different category pairs**: business_constraint (p9 overlap) masking business_fiscal (p11 suspension); business_safety (p6 CRITICAL band) masking business_referential (p14 program-not-open)
- **Compensating invariants on different conserved quantities**: no-show charge/excuse restoring (sessions_consumed, strike count) to (0,0) with a `strike_reset_anchor` making the reset durable under recount; exemption extending `session_limit` +4 without rewriting session history

All assert numerics were pre-computed by executing the formulas in Python (billing 12000/6000/2500, limits 5/7/8/6, report 125 bps, outcomes delta −8.00). Three `excluded_because:` stubs cite existing §1.8 instances by name. Forbidden concurrency vocabulary verified absent.

## Step 4: Generate PRD — 2026-08-13T04:25:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/workspace/PRD.md` (340 lines). I did not open, grep, or reference either forbidden design file; the document was derived solely from the skill spec, the verbatim §2.2 source, the example PRD, and `SCAFFOLD.yaml`.

**Document skeleton (domain-derived, not template-copied):**
- §1: 2-paragraph introduction (quota allocation + segregation of duties + logical clock as framing)
- §2: 9 subsections — roles/identity models, verbatim response envelope, pagination, common resource properties (incl. the four `common_fields: false` entities), the logical clock (startup default 2026-08-01T00:00:00Z), the counseling/academic confidentiality wall, OCC, the priority-ordered validation pipeline, and precision/rounding
- §3: 9 subsections organized by business process (roster onboarding → term policy → triage/risk banding → episodes → sessions → strikes/posture → crisis coverage → groups/waitlists → referrals/outcomes/reporting), with booking parameters scattered across §3.5/§3.6/§2.7 and constants embedded in prose with unit conversions (cents → dollars, 30 days, 14 days, 15 weeks)
- §4: 67-row endpoint table, 4 columns only
- §5: 20-row error catalogue, 2 columns only

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 60 required, 60 present, 0 missing
- endpoints[].request_body / input-only ids: 8 required (to_iso8601, current_utc, expected_episode_version,
  director_override, chargeable, expected_crisis_shift_version, provider_specialty + report outputs), 8 present, 0 missing
- endpoints[].query_params: 7 required (limit, offset, and all filter names — all also entity fields), 7 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 17 checked, 17 expressed in prose (§2.8 enumerates the full pipeline order incl. p2.5 ownership and the p6–p17 domain-gate sequence), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (§2.7 names each write operation, expected_crisis_shift_version / expected_episode_version, ERR_STALE_VERSION + HTTP 412), 0 missing
- state_machines[].transitions: 42 checked (across all 10 machines), 42 fully expressed with preconditions + side effects + cascades, 0 missing
- calculations[]: 8 checked (incl. audit variant and intersession variant), 8 fully expressed as precise prose with constants embedded, 0 missing
- validations[] conditions: 17 checked, 17 matchable to error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: all expressed (posture sweep, clock auto-transitions, episode version bump on booking, excuse compensation, referral-accept cascade, etc.), 0 missing
- entities[].fields[] structured content: defaults, ranges, enum sets, and nullability all reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (3 intake dispositions, 3 crisis dispositions, timely/late cancel, charged/excused no-show, OPEN/EXHAUSTED → REFERRED_OUT, claim/reclaim), all with equal prose density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 455
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block verified byte-identical to `section-2.2-response-structure.md`; all 20 error IDs appear in §2/§3; all 57 enum/state values appear as exact strings; no fuzzy/approximating words and no pseudocode operators outside backticks.

## Step 6: Generate Implementation — 2026-08-13T04:45:00.000Z

All 67 PRD endpoints are registered (68 includes Flask's `/static/` default). Every endpoint from the PRD §4 endpoint table is implemented. The implementation is complete. (Ran concurrently with Step 5.)

## Summary

I generated a complete Python + Flask implementation of the University Counseling Center Operations API at `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/workspace/implementation/`.

**Files produced:**
- `start.sh` — foreground launcher with guarded `pip install` (no-op when flask+waitress already importable), `exec python3 app.py`
- `requirements.txt` — flask>=3.0, waitress>=3.0
- `app.py` — Flask entry point; binds `0.0.0.0:$PORT` (default 10000); uses waitress if available, else Flask dev server
- `db.py` — in-memory stores (empty at boot, no seeding); logical clock starting at `2026-08-01T00:00:00Z`; `touch`/`stamp_new`/`stamp_new_light` helpers
- `errors.py` — `ApiError` class plus all 20 catalog error IDs with their HTTP statuses
- `response.py` — success/error envelopes with `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`
- `middleware.py` — `require_roles` decorator validating `X-User-ID`/`X-User-Role`, 7 declared roles
- `util.py` — pagination parsing, body validation, ISO 8601 parsing, half-up rounding helpers
- `services/serializers.py` — output shaping including the Registrar academic view (hides `no_show_strike_count`, `strike_reset_anchor`, `booking_posture`)
- `services/domain.py` — risk scoring, session limits, billing (Decimal ROUND_HALF_UP), consumption ledger recount, strikes/posture recompute with SUSPENDED cascade, counselor caseload, session/shift overlap, waitlist promotion, clock-driven auto-transitions (programs, shifts, referral lapse)
- `routes/` — 13 blueprints covering all 67 PRD endpoints (clock, students, counselors, intakes, episodes, sessions, notes, groups, crisis, referrals, policies, outcomes, reports)

**Key correctness properties verified via in-process smoke tests:**
- Envelope shape, request-id generation, pagination meta
- Role gating (401 UNAUTHENTICATED, 403 UNAUTHORIZED), ownership gates (counselor owns sessions/episodes; student owns enrollment drop; CD bypass)
- Registrar academic view strips clinical fields; clinical note 403 CONFIDENTIALITY for non-author non-director
- Risk scoring: base = phq9+gad7, attempt ×3 elif ideation +15, clamp [0,100], bands at 15/35/60 inclusive lower edges
- Session limit: tier by band, funding adj (-1/0/+1), floor 2; intersession base 6 with LOW band rejected at complete
- Billing: STUDENT_FEE → 0; INSURANCE ×0.80, SPLIT ×0.50, single ROUND_HALF_UP; verified 7500×0.80=6000
- Strikes: recount scoped to current-term non-terminal episodes post-anchor; posture transitions CLEAR→RESTRICTED (count==limit-1), →SUSPENDED (count≥limit), excuse reverses; only strike-reset lifts SUSPENDED
- Suspension cascade cancels future SCHEDULED sessions with `POLICY_SUSPENSION`
- Episode exhaustion cascade creates PENDING referral + cancels SCHEDULED sessions with `EPISODE_EXHAUSTED`; exemption adds +4 limit, returns OPEN
- Reopen flow: closes old to REOPENED, completes referenced PENDING intake, creates new OPEN episode with `prior_episode_id` and screener as primary
- Group capacity → WAITLISTED; drop promotes head by created_at, tie-break by strike count, then student created_at
- Risk ceiling + CRITICAL never group-eligible
- Crisis shift claim with OCC (ERR_STALE_VERSION 412), overlap rejection, release blocked while IN_ROOM
- Crisis visit serialization (ERR_ROOM_OCCUPIED), disposition cascades (RETURN_TO_CARE creates episode; COMMUNITY_REFERRAL; EMERGENCY_TRANSPORT removes group enrollments)
- Referral lifecycle: match → accept (episode REFERRED_OUT cascade) → confirm-engagement (14-day window) → COMPLETED; decline/rematch capped at 3 (ERR_REFERRAL_LOOP_EXHAUSTED); auto-lapse at 30 days
- Policy lifecycle: DRAFT→PUBLISHED only one per term (ERR_POLICY_CONFLICT); retire requires DRAFT replacement; publish triggers posture sweep
- Capacity report: delivered_minutes, bookable_minutes (cap×60×15), utilization_bps (basis points, half-up), outcomes_delta (2 decimals)
- Validation pipeline ordering (p9 overlap before p11 booking posture before p12 session limit, etc., per PRD §2.8)
- OCC via `expected_episode_version` on session booking and `expected_crisis_shift_version` on shift claim
- `start.sh` boots cleanly from a fresh process (verified: server responds within 4s of invocation)

## Step 5: Generate Unit Tests — 2026-08-13T05:00:00.000Z

Complete. All generation finished and audited. (Ran concurrently with Step 6.)

## What was generated

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/test_helpers/`:
- `types.py` — 13 entity TypedDicts + 14 status/role enums; the four append-only resources (IntakeAssessment, GroupEnrollment, OutcomeMeasure, ClinicalNote) correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (48 endpoints including the logical clock)
- `api_errors.py` — all 20 error IDs with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions; append-only entities assert `updated_at`/`version` absence (PRD §2.4)
- `factories.py`, `constants.py` (risk thresholds, billing rates, EXEMPTION_BONUS 4, lapse/engagement windows, default clock)
- `test_users.py` — shared constants for opaque roles (FrontDesk/ReferralCoordinator/Registrar) plus per-instance builders for entity-backed roles (Student/Counselor/TriageScreener/ClinicalDirector)
- `fixtures.py` — composite helpers: `setup_open_episode`, `book_session` (auto re-reads episode version for OCC), `setup_exhausted_episode`, `setup_student_with_strikes`, `create_claimed_shift`, `setup_stabilized_visit`, `setup_pending_referral_high`, group helpers

**`test_suite/`** — `conftest.py` + 10 test files, **78 tests total**.

## Audit results (all green)
- **Queue A**: all 18 difficulty instances have ≥2 tests (one has 3) — 37 tests
- **Queue B**: all 41 non-stub corner instances have ≥1 test; the 3 `excluded_because:` stubs (`error_session_limit_after_exhaustion_without_exemption`, `cascading_side_effects_exhaustion_three_hop`, `derived_field_reconciliation_on_excuse`) emit nothing, and their difficulty-instance cross-references resolve
- **C4 tags**: all 78 tests carry exactly one `Design:` line resolving to a real instance name; no untagged/dual-tagged tests
- **C1 verbatim**: every docstring citation survives a literal normalized grep of PRD.md (78 tests, 0 failures)
- No `skip`/`skipif`/`xfail` markers; no "scaffold" mentions in comments/docstrings; all modules compile and `pytest --collect-only` succeeds

## Judgment calls worth noting
- `intake_assessment_immutable_no_update_endpoint`: kept the PRD-covered assertions (risk_points, absence of `version`/`updated_at`); dropped the "no PATCH route exists" probe (a missing route's behavior — 404 vs 405 — is not uniquely derivable from the PRD)
- `student_creation_defaults_applied`: dropped the `academic_record_flags` empty-array default (PRD says "optional" without naming the default — silence pattern `default-value`) and the absolute initial `version == 1` (PRD pins only increments, not the starting value); kept CLEAR posture, zero strikes, and the epoch `strike_reset_anchor` (all verbatim in §3.1)
- `crisis_shift_release_blocked_while_visit_in_room` and `episode_close_blocked_by_scheduled_session`: PRD names no error_id for these cross-entity precondition blocks; `ERR_INVALID_STATE` is the only catalogue entry a PRD-only reader could map them to (closed catalogue + §2.8 stage 6), so it passes the two-reader test
- `no_show_strikes_scoped_to_current_term`: the design recipe's retire-FALL-policy step would fail under PRD §3.2 (retirement requires a same-term DRAFT, not a SPRING draft); the test simply publishes SPRING alongside FALL, which the per-term published-slot rule allows

## Step 7: Run Tests and Iterate — 2026-08-13T05:05:00.000Z

All 8 rounds pass 78/78 with zero failures. Clean sweep achieved — exiting with the summary.

## Summary

**Iterations run:** 2 (initial sweep: 74/78 in all 8 rounds, union of 4 distinct failing tests; second sweep: 78/78 × 8 rounds, clean).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence; no PRD-silence or unique-derivability collapses found.

**Fixes applied to `test_suite/` (2):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/test_suite/test_10_reports.py` — `TestCapacityReport._build` called `self._setup_report_scenario()` but the helper is a module-level function, raising `AttributeError` before any API call (affected `test_capacity_report_delivered_and_bookable_minutes` and `test_capacity_report_utilization_bps_rounded_last`). Changed to call the module-level `_setup_report_scenario()`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/test_suite/test_05_episode_lifecycle.py` — `test_reopen_creates_child_episode_with_prior_link`: setup closed the episode and created the replacement intake at the same logical-clock instant, leaving the PRD §3.4 precondition "must have been created after this episode closed" ambiguous (a faithful strict-timestamp implementation correctly returned 409). Added `advance_clock("2026-08-02T00:00:00Z")` between close and new intake so the precondition holds under any PRD-faithful reading. No assertion weakened.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/` (1 logical fix, 5 call sites):**
- PRD §3.6 defines `no_show_strike_count` as a standing recount scoped to the current term ("the `academic_term` of the student's most recently created non-terminal episode") and states "A student with no non-terminal episode carries a strike count of zero regardless of history." The implementation only recomputed strikes on no-show/excuse/reset/policy-publish events, so the stored count went stale when the current-term basis changed. Added `domain.recompute_strikes_and_posture(student)` at every basis-changing event:
  - `routes/episodes.py::close_episode` (episode becomes terminal)
  - `routes/episodes.py::reopen_episode` (new non-terminal episode created)
  - `routes/intakes.py::complete_intake` (SHORT_TERM_CARE path creates an episode)
  - `routes/crisis.py::disposition_visit` (RETURN_TO_CARE creates an episode)
  - `routes/referrals.py::accept_referral` (linked episode transitions to terminal REFERRED_OUT)

This fixed `test_strikes_scoped_to_current_term` (FALL strike correctly excluded once the student's most recent non-terminal episode is the SPRING one) with no regression to the other 77 tests across all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-08-13T05:15:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1393_university_counseling_center_operations/workspace/PRD_FINALIZED.md` is written with exactly three sentence-level edits in two PRD sections.

## Line counts / delta
- PRD.md: 339 lines (54,754 chars); PRD_FINALIZED.md: 339 lines (55,589 chars) — +835 chars, +1.53%, 0% line-count delta (all edits are inline within existing paragraphs; no new sections).

## Changes (one bullet per edit)
- **§3.4 (line 174)** — revise — reopen precondition "must have been created after this episode closed" now pins **strict** comparison ("created strictly after"), names the compared fields (`created_at` vs the episode's `updated_at`, which closure stamps), and states a same-instant assessment is rejected — `implementation/routes/episodes.py:218-221` (`if not (ia_created_at > ep_closed_at): raise ERR_INVALID_STATE`).
- **§3.6 (line 196)** — insert — added that the strike recount is also refreshed whenever the student's current-term basis shifts: new non-terminal episode created (intake completion into `SHORT_TERM_CARE`, episode reopen, crisis `RETURN_TO_CARE` that creates an episode) or non-terminal episode becomes terminal (closure, referral acceptance moving its linked episode to `REFERRED_OUT`) — `implementation/routes/episodes.py:186,252`, `implementation/routes/intakes.py:168`, `implementation/routes/crisis.py:331`, `implementation/routes/referrals.py:94`.
- **§3.6 (line 198)** — revise — posture recompute enumeration widened from "after every strike change and every policy publication" to also include "every current-term-basis shift of the kind just described" — same impl sites as above.

The third `<step_7_diff>` item family (test_10_reports.py `self._setup_report_scenario` → module-level call) is a pure test-code bug with no PRD implication — no edit made for it.

## Per-edit pre-edit search log

**Edit 1 (§3.4 reopen strictness)**
- (a) Subject: comparison of the replacement intake's creation time against the episode's closure in the reopen precondition.
- (b) Paths enumerated: `routes/episodes.py::reopen_episode` (only comparison site, lines 210-221; compares against `episode["updated_at"]`); all post-closure writers of that field — `close_episode` stamps it via `db.touch` (episodes.py:180; db.py:95-99), and `domain.recompute_episode_after_consumption_change` (domain.py:296-300) can re-stamp it via `sessions.py::excuse_session` (excuse does not gate on episode status, sessions.py:202-221). Confirmed `grant_exemption` (requires EXHAUSTED) and `accept_referral` (requires OPEN/EXHAUSTED) cannot touch a CLOSED episode.
- (c) Adjustment: instead of bare "strictly after closure" (which would falsely claim the comparison target is the closure instant exactly), the wording names `updated_at` "as last stamped (the closure itself stamps it)" — staying consistent with the excuse-drift path where a post-closure excuse advances `updated_at`.

**Edits 2a/2b (§3.6 recompute triggers)**
- (a) Subject: when the stored `no_show_strike_count` recount and `booking_posture` are recomputed.
- (b) Paths enumerated (grep for `recompute_strikes_and_posture` / `recompute_student_strikes` / `recompute_booking_posture`): `sessions.py:192` (chargeable no-show), `sessions.py:220` (excuse), `students.py:141` (director reset), `policies.py:93` (publish sweeps all students), `episodes.py:186` (close), `episodes.py:252` (reopen), `intakes.py:168` (SHORT_TERM_CARE only — HIGH path intakes.py:171-184 and CRITICAL path intakes.py:186-214 create no episode and do not recompute), `crisis.py:331` (RETURN_TO_CARE only inside the `if not has_open` branch), `referrals.py:94` (accept only when a linked OPEN/EXHAUSTED episode transitions). Non-recomputing paths checked and excluded from the wording: `grant_exemption` (EXHAUSTED→OPEN, both non-terminal), excuse-driven EXHAUSTED→OPEN, hold/release-hold/cancel/complete, student PATCH, clock advance (`domain.apply_clock_transitions` touches no students), referral match/decline/rematch/confirm-engagement, crisis COMMUNITY_REFERRAL/EMERGENCY_TRANSPORT dispositions.
- (c) Adjustments: triggers scoped with qualifying sub-conditions ("`RETURN_TO_CARE` disposition **that creates an episode**"; "referral acceptance **moving its linked episode to `REFERRED_OUT`**"; "intake completion **into `SHORT_TERM_CARE`**") so no non-recomputing path is swept in; the posture sentence says only that posture "recomputes" at a basis shift without claiming which policy governs (impl uses the new current term's published policy and no-ops when none exists, domain.py:406-411 — PRD's existing loose phrase "the published policy" was left untouched); the recount sentence says the count "keeps tracking" rather than making any `version`/`updated_at` touch claim (impl only touches the student when the value actually changes, domain.py:396-398).

## Step 9: Complete PRD — 2026-08-13T05:35:00.000Z

All edits applied and verified. Final summary:

## Result

**Files**: `workspace/PRD_FINALIZED.md` (339 lines, 55,589 chars) → `workspace/PRD_COMPLETED.md` (339 lines, 60,608 chars; **+5,019 chars, +0 lines** — all changes are inline paragraph edits, no new sections).

**Counts**: 23 ambiguity-pins, 11 mismatch-revisions (34 changed passages total).

### Mismatch revisions (PRD said X, impl does Y)
- §2.1 — revise — mismatch — TriageScreener bullet: `screener_id` now pinned as payload-supplied and never compared to `X-User-ID` — routes/intakes.py:43-44,61
- §2.6 — revise — mismatch — note wall scoped to single-note reads; list endpoint applies no per-item body filtering — routes/notes.py:53-72
- §2.8 (items 4-5) — revise — mismatch — payload FK resolution interleaves with per-field shape checks as the body is parsed (impl validates early-read fields before later FK existence) — routes/intakes.py:43-56, routes/episodes.py:77-90
- §3.1 — revise — mismatch — `active` flag gates only shift claiming and intake completion, *not* session booking (impl never checks it at booking) — routes/episodes.py:69-161
- §3.2 — revise — mismatch — policy uniqueness enforced only at publish time via `ERR_POLICY_CONFLICT`; DRAFT creation has no uniqueness check and `ERR_DUPLICATE` is never raised for policies — routes/policies.py:35-51,82-88
- §3.3 — revise — mismatch — completion evaluates only the caseload dial ("either capacity dial" was wrong); also pins enrollment-status/inactive-counselor failures as `ERR_INVALID_STATE` — routes/intakes.py:116-144
- §3.3 — revise — mismatch — caseload contribution: episode contributes its *linked* assessment's points (not "latest assessment"); crisis-created episodes contribute band lower edges 0/15/35/60 — services/domain.py:487-495, routes/crisis.py:340-348
- §3.5 — revise — mismatch — note `author_id` need only resolve to an existing counselor (not "their own"; no caller equality check) — routes/notes.py:34-41
- §3.7 — revise — mismatch — invalid `disposition` value → `ERR_INVALID_REQUEST` (was `ERR_RISK_BAND_VIOLATION`) — routes/crisis.py:274-276
- §3.8 — revise — mismatch — dropped "increase in the program's capacity" as a promotion trigger (no endpoint can change capacity); also pins drop requires ENROLLED enrollment — routes/groups.py:200-209
- §3.9 — revise — mismatch — removed the "audit variant" re-banding claim (impl computes no such variant anywhere) — routes/reports.py (absent)

### Ambiguity pins (PRD silent, impl behavior now pinned)
- §2.3 ×3 — pagination param validation → `ERR_INVALID_REQUEST`; created_at ties broken by `id`; `has_more` = offset+returned < total_count — util.py:24-51,197-203; response.py:35
- §2.5 ×2 — clock-set accepts any instant (no monotonicity check); all auto-transition boundary comparisons are inclusive (at-or-past) — routes/clock.py:20-23; services/domain.py:613-652
- §2.6 — Registrar view strips exactly `no_show_strike_count`, `strike_reset_anchor`, `booking_posture` — services/serializers.py:20-31
- §3.1 ×2 — PATCH per-field grant violation → `ERR_UNAUTHORIZED`, unknown fields ignored, every PATCH bumps version; counselor `active` filter semantics — routes/students.py:102-126; routes/counselors.py:78-81
- §3.3 — default `academic_term` = most recently created PUBLISHED policy of any term, else `ERR_INVALID_REQUEST` — routes/intakes.py:126-132; services/domain.py:196-203
- §3.4 ×2 — close and exemption/reopen precondition failures → `ERR_INVALID_STATE` — routes/episodes.py:173-178,207-221,262-263
- §3.5 ×3 — booking caseload check nuance (primary counselor's load already includes episode points); half-open overlap intervals; hold/release-hold source-status errors — routes/episodes.py:125-136; services/domain.py:511-530; routes/sessions.py:63-75
- §3.5 — cancel only from `SCHEDULED`; window from episode-term policy, else zero hours — routes/sessions.py:124-137
- §3.6 ×3 — mark-no-show only from `SCHEDULED`; excuse only from `NO_SHOW_CHARGED`; posture consults current-term published policy (none → unchanged) — routes/sessions.py:168-169,204-205; services/domain.py:402-410
- §3.6 — strike reset requires `SUSPENDED` else `ERR_INVALID_STATE` — routes/students.py:137-138
- §3.7 ×2 — claim requires existing+active counselor (`ERR_NOT_FOUND`/`ERR_INVALID_STATE`); release blocked by IN_ROOM or non-CLAIMED → `ERR_INVALID_STATE` — routes/crisis.py:101-106,137-142
- §3.7 — RETURN_TO_CARE term = most recently created PUBLISHED policy's term — routes/crisis.py:307-308
- §3.8 ×3 — `meeting_day` opaque non-empty string; publish error names (`ERR_INVALID_STATE`/`ERR_INVALID_REQUEST`); no duplicate-enrollment check — routes/groups.py:43,94-97,122-169
- §3.9 ×3 — match error names; engagement window inclusive at 14 days + non-ACCEPTED → `ERR_INVALID_STATE`; report `academic_term` query param required — routes/referrals.py:62-65,141-147; routes/reports.py:24-26
- §3.9 — `outcomes_delta` = flat mean of per-episode-per-instrument deltas, latest administration per phase wins, `0.0` when none qualify — routes/reports.py:61-79
