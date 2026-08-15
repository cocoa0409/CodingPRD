# Worklog — task_1884_academic_advising_caseload_management

## Step 1: Create Task Directory — 2026-08-14T22:53:00.000Z

Directory `tasks/task_1884_academic_advising_caseload_management/` and `workspace/` pre-created by pipeline launcher (per command args). Index 1884 assigned externally; no scan performed.

## Step 2: Generate Scaffold — 2026-08-14T23:26:00.000Z

Scaffold generation complete. All three artifacts are written and lint-clean.

## Generated files
- `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Counts
- Entities: 10 (Advisor, Student, AdvisorAssignment, Appointment, DropInTicket, EarlyAlertReferral, Intervention, RegistrationHold, DegreePlan, AdvisingNote)
- State machines: 6 (assignment, appointment, drop-in ticket, referral, hold, degree plan)
- Calculations: 9 (caseload_load dual-variant, retention_rate dual-variant, at_risk_score, term_credit_mapping, outreach_sla_due_at, queue_position, advisor_scheduled_minutes, advising_requirement, registration_clearance)
- Validations: 10 ordered priority rows (incl. an OCC row at 4.5)
- Endpoints: 50 (incl. `/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z, and `/advising/ops/daily-close` ops sweep)
- Errors: 38
- Roles: 4 (AdvisingDirector opaque, Advisor entity_backed:Advisor, FrontDeskStaff opaque, FacultyReferrer opaque; hierarchical_override model)
- Difficulty-design instances: 18 (9 rules × 2)
- Corner-design instances: 58 total = 40 active + 18 `excluded_because` stubs
- Concurrency rules: 1 (OCC on Student.version for create-with-supersede assignment, ERR_STALE_VERSION/412)

## Lint verdict (verbatim)
`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (272 calls scanned)

## Notable design decisions
- **Archetype**: temporal windowing (half-open appointment overlap, ±10min check-in window, strict-> SLA breach) + compliance/audit secondary (CONFIDENTIAL notes with author/director-only visibility, ownership-gated record writes). Flat topology; Expert band chosen because the scenario names 8 distinct workflows.
- **Rule-satisfying mechanics**: dual variants on different domains (advisor load HEADCOUNT-vs-WEIGHTED ranking with divergent winners; retention COHORT_PERSISTED 0.5000 vs TERM_OVER_TERM 0.3333 on identical rows); combinatorial modes (a) conditional-band at_risk_score = literal 98 and (b) per-term-then-sum credit rounding 22 vs 21; cycles on DegreePlan (SUBMITTED→DRAFT) and Referral (OUTREACH_IN_PROGRESS⇄NO_RESPONSE with auto-escalation at 3 attempts); depth-3 cascade (escalate→Intervention→risk tier→flag/requirement/clearance) vs depth-2 hold-release→clearance cascade; priority conflicts on different category pairs ({state, business_temporal} and {state, business_safety}); boundaries on count capacity vs timestamp strict->; overlap rules with different semantics (half-open interval on advisor schedule vs instantaneous day-capacity count on the queue); invariants conserving assignment count vs scheduled minutes.
- **Selector policies fully pinned** (eligibility/ranking/tie-break/empty-pool) for auto-assign (created_at tie-break, never id) and drop-in call-next (lowest position).
- **Lint-driven fixes**: quoted `errors[...]`-style grounds tokens for YAML flow sequences; renamed student path param to `{id}` to satisfy the FK sub-resource check; added `PATCH /advisors/{id}` to close the Advisor.status enum (INACTIVE was unreachable) and make ERR_ADVISOR_NOT_ACTIVE triggerable, plus a corner instance covering it.

## Step 3: Copy Shared Files — 2026-08-14T23:27:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1884_academic_advising_caseload_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T23:42:00.000Z

All checks complete. The PRD is written and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/workspace/PRD.md` — 324 lines.

### PRD section list
- **§1 Introduction** (2 paragraphs — business-context angle)
- **§2 Global Specifications** (10 subsections): 2.1 User and Role-Based Access Control (all 4 roles, `identity` translated per role) · 2.2 API Response Structure (verified **byte-identical** to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Nested Resource Retrieval · 2.7 Derived Fields and Immediate Recomputation · 2.8 Numeric Precision and Rounding · 2.9 Optimistic Concurrency Control · 2.10 Evaluation Order of Request Checks
- **§3 Business Logic & Workflows** (9 subsections): advisor roster/load · student intake & at-risk score · assignment (manual + OCC + supersede + auto-assign selector) · appointments · drop-in queue · referrals & outreach protocol · interventions · holds/degree-plans/clearance · notes/retention/daily-close
- **§4 Endpoint Definitions** — 50-row table, 4 columns only
- **§5 Error Code Catalogue** — 38-row table, 2 columns only

### Scaffold rules covered
All of them: 10 entities (55 field names incl. common fields), 6 state machines / **26 transitions** (all from→to pairs, preconditions, side effects), **9 calculations** (at-risk score with GPA bands/boosts/caps, caseload load with both ranking variants, retention with both variants, pinned term-rounding with the 10.5+10.5=22-vs-21 example, SLA due/breach with strict-> boundary, queue position, scheduled minutes, advising requirement, registration clearance), **10 validation priorities** (rendered as an explicit numbered pipeline with cross-step consequence examples), **1 OCC rule** (`expected_student_version` / `ERR_STALE_VERSION` / 412, no race framing), all **50 endpoints**' inputs/side effects, all **38 error IDs** (each appears in §2/§3 prose *and* the §5 table), all 4 roles with identity semantics.

### Hard Contract reports
- **Contract 1 (Field-Name Coverage): PASS** — fields 55/55, body params 33/33, query params 19/19, path params 9/9, errors 38/38, state values 21/21 (mechanically verified; one heuristic false positive "SLA" from a description string, not an enum value).
- **Contract 2 (Rule Coverage): PASS** — priorities 10/10, OCC 1/1 (endpoint + field + error + status all named), transitions 26/26, calculations 9/9, validation conditions 10/10 matchable, endpoint side effects 50/50, field structured content (defaults/initials/constraints) reconstructible, sibling branches symmetric (NO_ANSWER ×3, REACHED ×3, LEFT ×2, CLOSE ×2, escalate ×3, ranking variants ×2, retention variants ×2).
- **Contract 3 (§3 Path Purity): PASS** — 471 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos. Also verified: no operator pseudocode (`==`, `>=`, `min(`, `IN {`…), no fuzzy words ("approximately"/"about"/"around"…), PRD ends at §5 with no audit footer.

### Zero-Silence Rule notes (prose decisions beyond literal scaffold text)
1. §2.7 renders `complexity_profile.consistency_model: immediate` as a general principle — profile-level, not a table row.
2. §2.10's pipeline adds consequence phrasing ("a creation that fails both the version guard and a later eligibility check reports `ERR_STALE_VERSION`") — derived from priority ordering, not literal scaffold text.
3. Stated the explicit negation that auto-assign does **not** take `expected_student_version` (per the skill's OCC rule for unlisted endpoints).
4. Nested `terms` JSON keys (`term_code`, `courses`, `course_code`, `credits`) were surfaced from the field *description* text since they aren't `fields[].name` entries.
5. "ON_LEAVE students may still receive notes" — derived from the `ERR_STUDENT_INACTIVE` condition naming only `INACTIVE`.
6. Retention pool "any `care_status`" wording taken from `calculations[].input_set`; section grouping/titling (clock as §2.4, 9 workflow subsections) is my own organization per the diversity rules.

### Design-file constraint
Confirmed: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-15T00:05:00.000Z

Generation complete. Summary below.

## Test infrastructure — `tasks/task_1884_academic_advising_caseload_management/test_helpers/`

| File | Contents |
|---|---|
| `types.py` | 17 status/role enums + TypedDicts for all 10 entities (all carry full common fields per PRD §2.5) |
| `api_client.py` | `ApiClient(GenericApiClient)` with one method per endpoint (49 methods: clock, advisors, students, assignments + auto-assign, appointments, drop-in queue, referrals, interventions, holds, degree plans, notes, retention report, daily-close) |
| `api_errors.py` | `ApiErrorId` (38 ids) + HTTP status map registered via `set_error_http_status_map` |
| `assertions.py` | Per-entity `assert_*` + `assert_student_risk_invariants` (tier/score band agreement) |
| `factories.py` | Payload factories, input fields only; `course()`/`term()` builders for degree plans |
| `constants.py` | GPA bands, severity boosts, weights, SLA days, MAX_TERM_CREDITS=18, queue cap 3, clock default |
| `test_users.py` | `TEST_USERS` for the 4 roles + `make_advisor_headers(id)` (entity-backed role) + `make_ghost_headers` |
| `fixtures.py` | Composite setups: OCC-safe `create_manual_assignment` (fresh version read), `setup_divergent_caseload_pool`, `setup_retention_cohort_2025`, `setup_student_at_score_98`, `setup_escalation_candidate`, `setup_student_with_two_advisors`, `check_in_and_complete`, etc. |

## Test suite — `test_suite/` (76 tests, all collected cleanly by pytest)

| File | Tests |
|---|---|
| test_01_student_intake_envelope_and_pagination.py | 7 |
| test_02_advisor_assignment_and_selector.py | 11 |
| test_03_appointment_book.py | 13 |
| test_04_dropin_queue.py | 7 |
| test_05_referral_outreach_protocol.py | 9 |
| test_06_holds_degree_plans_clearance.py | 14 |
| test_07_notes_and_access_control.py | 9 |
| test_08_risk_score_and_retention.py | 6 |

## Coverage vs design indices

- **§1.8 Difficulty: 18/18 instances translated, 0 skipped** — 2 tests each (36 tests). Each pair splits into primary-outcome + side-effect/boundary-companion tests (e.g., HEADCOUNT winner vs WEIGHTED winner; admit at `max-1` vs exclude at `max`; breach at `due_at`+1s vs not-breached at `due_at`−1s/`due_at` exact).
- **§1.9 Corner: 40/40 non-stub instances translated, 0 skipped** — 1 test each. All 18 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.
- **Design tags:** every one of the 76 tests carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line as the final docstring line, verified programmatically to resolve against the source yamls.
- **Citations:** 131 PRD citations across the 76 docstrings all survive normalized literal grep of PRD.md (fixed 4 initial mismatches from bold headings/table rows).

## Judgment calls (PRD-first filter)

- The PRD says `version` "increments with every modification" without pinning the initial value, so design-asserted absolute version literals (`e1_v == 1`, `v4 == 6`, etc.) were relaxed to the PRD-derivable form: exact `+1` deltas where the PRD verbatim states "increments ... by 1" (student updates §3.2, assignment events §3.3), monotonic `assert_version_incremented` where it doesn't (degree-plan edits). No instance was weakened in its core claim.
- Retention `rate` is asserted numerically via `pytest.approx` after `float()` coercion, since PRD pins "four decimal places, round-half-up" but not the JSON representation type.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/table references in comments; no freelance tests beyond the two indices.

## Step 6: Generate Implementation — 2026-08-15T00:05:00.000Z

Fresh-boot isolation verified: boot 2 starts with an empty store (0 advisors) and the logical clock reset to 2026-08-01. The implementation is complete and working.

## Summary

**Implementation location:** `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/workspace/implementation/`

### File list
- `start.sh` — executable launcher (guarded pip install + `exec python3 app.py`)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app entry, blueprint registration, global ApiError/404/405/500 handlers
- `db.py` — in-memory stores (10 dicts) + logical clock state (default `2026-08-01T00:00:00Z`)
- `errors.py` — `ApiError` class + all 37 error-ID constants from the scaffold catalog
- `response.py` — envelope helpers producing exact `{meta: {api_request_id, api_request_timestamp, [limit/offset/total_count/has_more]}, response_type, data}` structure; error body uses `error_id`/`message`
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) and role-list check (403 `ERR_UNAUTHORIZED_ROLE`)
- `services/common.py` — UUID/timestamp stamping, `version` bumps, ISO parsing, pagination (limit 1–100 default 10, offset ≥ 0), JSON body validation
- `services/calculations.py` — all calculation logic
- `routes/` — `advisors.py`, `students.py`, `assignments.py`, `appointments.py`, `dropin.py`, `referrals.py`, `interventions.py`, `holds.py`, `degree_plans.py`, `notes.py`, `ops.py` (clock + retention + daily-close)

### Endpoint count
All **49 endpoints** from the scaffold endpoint table are implemented (clock set, 4 advisor, 4 student, 5 assignment, 6 appointment, 6 drop-in, 6 referral, 4 intervention, 3 hold, 7 degree-plan, 2 note, retention report, daily-close).

### State machine count
**6 state machines** implemented: AdvisorAssignment (ACTIVE→ENDED manual/superseded), Appointment (SCHEDULED→CHECKED_IN→COMPLETED, SCHEDULED→CANCELLED, SCHEDULED→NO_SHOW via sweep), DropInTicket (QUEUED→CALLED→SERVED, QUEUED/CALLED→LEFT incl. day-boundary sweep), EarlyAlertReferral (OPEN/OUTREACH_IN_PROGRESS/NO_RESPONSE cycle, RESPONDED, ESCALATED manual + auto at 3 attempts, CLOSED), RegistrationHold (ACTIVE→RELEASED with plan gate), DegreePlan (DRAFT→SUBMITTED→APPROVED, SUBMITTED→DRAFT return cycle).

### Calculation count
**8 calculations** implemented per scaffold Table 1.3: `caseload_load` (headcount + weighted variants for auto-assign ranking), `retention_rate` (COHORT_PERSISTED + TERM_OVER_TERM, 4dp ROUND_HALF_UP, denominator-0 rule), `at_risk_score` (GPA bands 40/25/10, max-severity referral boost, no-show cap 3, +10/intervention, +8/hold, cap 100, tier thresholds 70/40), `term_credit_mapping` (pinned round-per-term-then-sum, verified 10.5+10.5→22), `outreach_sla_due_at` (2/5/10 days, strict `>` breach boundary), `queue_position` (1+count per queue_date), `advisor_scheduled_minutes` (SCHEDULED/CHECKED_IN only), `advising_requirement` + `registration_clearance` (with HIGH-tier auto-flag cascades).

### Storage
**In-memory only** — plain module-level dicts in `db.py`, no database, no file persistence, and **zero seeding at startup**. Verified fresh-boot isolation: a second `start.sh` invocation starts with an empty store and the logical clock back at its 2026-08-01 default, matching the per-test-server restart contract.

### start.sh mechanics
Reads `$PORT` (default 10000), binds `0.0.0.0` via Flask. Dependency install is guarded (`if ! python3 -c "import flask"`) so per-test reboots skip pip entirely; the final server command uses `exec python3 app.py` so signals propagate and the script stays foreground.

### Notable design decision
All resource timestamps (`created_at`, `updated_at`, `checked_in_at`) read the server-side **logical clock** rather than wall clock, making `due_at = created_at + SLA_DAYS` deterministic under `/_clock/set_current_utc` — verified that SLA breach is false exactly at `due_at` and true one second past, and that the daily-close no-show sweep fires the full risk cascade (score 40 after +20 HIGH referral + 10 no-show on a 3.5-GPA student).

## Step 7: Run Tests and Iterate — 2026-08-15T00:30:00.000Z

## Summary

**Result: clean 8-round parallel sweep — all 8 rounds 76/76 passed.**

- **Iterations run: 2** (initial sweep surfaced the failures; one fix round; second sweep clean across all 8 rounds).

**Failure analysis (iteration 1 union):**
- 5 degree-plan tests failed in all 8 rounds with `Setup step failed with HTTP 400: ERR_VALIDATION - Missing required field: terms`.
- `test_auto_assign_tie_break_uses_created_at` failed in rounds 1, 2, 3, 8 (flaky).

**Tests deleted: none.** Both failure clusters traced to test-artifact bugs, not PRD-silent assertions — every asserted rule is verbatim-covered by PRD §3.3 / §3.8.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/test_helpers/fixtures.py` — `create_draft_plan`: it passed `terms=None` into `create_degree_plan_payload`, and the factory's `defaults.update(overrides)` clobbered the default term list with `None`, emitting `"terms": null`. PRD §3.8 names `terms` a required input ("creates one under the student with a `catalog_year`, a `required_credits` total … and `terms`: a list of term entries"), so the implementation's `ERR_VALIDATION` was the PRD-correct rejection. Fixed by only overriding `terms` when the caller supplies one.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/test_suite/test_02_advisor_assignment_and_selector.py` — `test_auto_assign_tie_break_uses_created_at`: the test asserted "earlier `created_at` wins the auto-assign tie" (PRD §3.3: "ties broken by lower `assigned_active_count` and then by earlier `created_at`") but created both advisors under the frozen default logical clock, giving them identical `created_at` stamps — the PRD tie-break chain then fully ties and cannot determine a winner (the implementation's residual `id` fallback produced a random winner per boot). Fixed by advancing the PRD-declared logical clock (`/_clock/set_current_utc`, §2.4) by 1s between the two advisor creations, so `created_at` strictly orders them and the PRD sentence uniquely determines the winner for any faithful implementation.

**Fixes applied to `implementation/`: none.** All routes, calculations, cascades, and the §2.10 check ordering were verified PRD-faithful; no implementation change was needed.

**Diagnostic note for tooling:** mid-sweep stdout progress tokens are unreliable under 8-way concurrent writes to a shared output file (mid-line interleaving fabricates/losses outcome tokens — e.g. it showed phantom `FAILED` lines for `test_term_credit_rounding_per_term_then_sum` that no JUnit XML recorded). The per-round `results.*.json` files (parsed from each run's private `--junitxml`) are the only authoritative source and were used for the failure union.

## Step 8: Finalize PRD — 2026-08-15T00:40:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/workspace/PRD_FINALIZED.md` with exactly two inline sentence insertions; everything else is verbatim.

**Line counts / delta:** PRD.md 324 lines / 48,210 bytes → PRD_FINALIZED.md 324 lines / 48,656 bytes. 0% line delta; +0.92% character delta (two sentences appended in place, no sections added).

**Changes (one bullet each):**
- §2.4 — insert — appended "Resource `created_at` and `updated_at` stamps (§2.5) are likewise read from this clock, never from wall-clock time, so resources created or modified without an intervening clock advance carry identical timestamps." — `implementation/services/common.py:15-24` (`now_iso` reads `db.get_logical_clock_iso()`), `common.py:49-56` (`stamp_new`), `common.py:59-63` (`touch`).
- §3.3 — insert — appended "Under either mode, if `created_at` also ties — as it does whenever the candidates were created without an intervening advance of the logical clock — the winner is the candidate whose `id` is smallest in ascending string order." — `implementation/routes/assignments.py:135` and `:137` (both selector sort keys end in `a["id"]` ascending; `pool[0]` wins).

**Step-7 items requiring no edit:** the degree-plan `terms` failure was a pure `test_helpers/fixtures.py` bug (fixture emitted `"terms": null`). PRD §3.8 already names `terms` a required creation input and §2.10 step 2 already pins missing-required-field → `ERR_VALIDATION`; the implementation's rejection (`degree_plans.py:85` via `common.py:109-113`) is the PRD-correct behavior, and even an implementer treating `null` as present would still hit `_validate_terms` (`degree_plans.py:63-65`) → same `ERR_VALIDATION`/400. No pin needed; no edit made.

**Per-edit pre-edit search log:**

Edit 1 (§2.4 clock-source sentence):
- (a) Subject: which clock sources resource `created_at`/`updated_at` stamps.
- (b) Enumerated paths: `services/common.py:15-24, 49-56, 59-63` (all stamping flows through `now_iso` → logical clock); all ten mutating route modules import `stamp_new`/`touch` from `services.common` (grep-verified: advisors, students, assignments, appointments, dropin, referrals, interventions, holds, degree_plans, notes); `db.py:17-26` (clock state, default `2026-08-01T00:00:00Z`); `routes/ops.py:25-29` (setter). Other consumers — check-in window (`appointments.py:150`), sweep (`ops.py:91-92`), SLA flags (`referrals.py:25,116-117`; `ops.py:123-125`), `queue_date` (`dropin.py:35-36,50,106`) — are already PRD-pinned as logical-clock reads; `due_at` inherits the clock transitively from `created_at` (`referrals.py:86`, `calculations.py:187-189`); `checked_in_at` already pinned by §3.4.
- (c) Wording bounded to `created_at`/`updated_at` only ("likewise read from this clock"), leaving the three already-pinned consumers untouched and not redefining §2.4's earlier illustrative list.

Edit 2 (§3.3 residual `id` tie-break):
- (a) Subject: auto-assign selector winner when the PRD's three-key tie-break chain fully ties.
- (b) Enumerated paths: `routes/assignments.py:134-138` (WEIGHTED and HEADCOUNT sort keys both terminate in ascending `a["id"]`); `services/common.py:11-12` (ids are `str(uuid.uuid4())`, so ascending string order is lexicographic — matching the step-7 note that the winner was random per boot). Conflict checks: `services/common.py:89-94` (`paginate` sorts list endpoints by `(created_at, id)` — a separate subject under §2.3, which this edit does not touch); `routes/dropin.py:111` (call-next orders by `position`, and §3.5 already states "a ticket's `id` is never consulted for ordering"); grep for `sort|sorted` confirms no other ranking site exists.
- (c) Wording scoped explicitly to "under either mode" of the advisor selector rather than a universal tie-break rule — precisely to avoid contradicting §3.5's drop-in ordering and to avoid claiming anything about §2.3 list pagination; "ascending string order" chosen because ids are UUID strings.

## Step 9: Complete PRD — 2026-08-15T00:50:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1884_academic_advising_caseload_management/workspace/PRD_COMPLETED.md` produced — 15 paragraphs touched, all inline inserts/revisions, no new sections.

**Source vs output:** `PRD_FINALIZED.md` (324 lines, 48,656 chars) → `PRD_COMPLETED.md` (324 lines, 51,419 chars); char-delta **+2,763**, line count unchanged.

**Counts:** 15 ambiguity-pins, 3 mismatch-revisions (18 changes total).

**Changes:**

- §2.1 — revise — mismatch — scoped "director may perform every Advisor-gated operation" to endpoints whose role list includes the director (call-next is Advisor-only; a director caller gets `ERR_UNAUTHORIZED_ROLE`) — `implementation/routes/dropin.py:105`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative/non-integer `offset` rejected with `ERR_VALIDATION` (400) — `implementation/services/common.py:72-86`
- §2.3 — insert — ambiguity — created_at ties broken by `id` ascending — `implementation/services/common.py:91`
- §2.3 — insert — ambiguity — `has_more` ≡ `offset + len(items) < total_count` — `implementation/response.py:42`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation; every successful update/transition bumps it even when values are unchanged — `implementation/services/common.py:49-63`
- §2.9 — insert — ambiguity — non-integer `expected_student_version` → `ERR_VALIDATION`, evaluated at the guard step after existence — `implementation/routes/assignments.py:61-69`
- §2.10 step 2 — insert — ambiguity — null counts as missing; non-object body → `ERR_VALIDATION`; typed-field rules (integer `cohort_year`/`catalog_year`/`required_credits`, boolean flags, array `major_codes`, term/course structure with numeric credits); out-of-domain list-filter values → `ERR_VALIDATION` — `implementation/services/common.py:97-119`, `implementation/routes/students.py:59-64,101-113`, `implementation/routes/degree_plans.py:63-78,86-90`
- §3.2 — revise — mismatch — HIGH-tier flag set only when a recompute *moves* the tier from below HIGH into HIGH (not on every recompute landing in HIGH); requirement/clearance refresh on every risk recomputation — `implementation/services/calculations.py:134-138`
- §3.2 — revise — ambiguity — recompute trigger list extended: a referral becoming `RESPONDED` or `ESCALATED` also recomputes score/tier — `implementation/routes/referrals.py:149-163`
- §3.2 — insert — ambiguity — rollover: flag/term changes refresh requirement/clearance; multi-field updates apply the term change (with history append judged against pre-update `care_status`) before any `care_status` change — `implementation/routes/students.py:143-165`
- §3.4 — revise — ambiguity — duration validated at second precision ([900, 3600] seconds; 14:59 fails, 60:00 passes); `duration_minutes` floors elapsed seconds; boundaries stored normalized to UTC ISO 8601 with three fractional digits — `implementation/routes/appointments.py:50-57,91-93`
- §3.6 — insert — ambiguity — `is_sla_breached` filter treats `true`/`1`/`yes` (case-insensitive) as true, anything else false — `implementation/routes/referrals.py:114-117`
- §3.6 — insert — ambiguity — outreach attempts reflected only in `attempt_count`; per-attempt records and notes are not persisted — `implementation/routes/referrals.py:147-174`
- §3.6 — revise — mismatch — escalate's optional `reason` is accepted but not persisted on the referral — `implementation/routes/referrals.py:177-190` (no body read)
- §3.8 — insert — ambiguity — plan submit gates evaluated credits-sufficiency first, so a both-failing submission reports `ERR_PLAN_CREDITS_INSUFFICIENT` — `implementation/routes/degree_plans.py:177-184`
- §3.8 — insert — ambiguity — return's `reason` is required for validity but not persisted on the plan — `implementation/routes/degree_plans.py:205-218`
- §3.9 — insert — ambiguity — note-list confidentiality filter applies before pagination, so `total_count` counts only caller-visible notes — `implementation/routes/notes.py:79-86`
- §3.9 — insert — ambiguity — retention response's `cohort_year` echoes the supplied filter, null when unsupplied — `implementation/routes/ops.py:78-84`

Everything else in the implementation (envelope shape, logical clock, advisor load formulas, create-with-supersede, selector tie-breaks, half-open overlap rule, check-in window, queue position/capacity rules, SLA due_at computation, escalation cascade, hold release ordering, plan rounding order, daily-close tallies, error catalog) was already uniquely pinned by the PRD and left untouched.
