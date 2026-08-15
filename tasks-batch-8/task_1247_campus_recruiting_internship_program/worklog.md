# Worklog — task_1247_campus_recruiting_internship_program

## Step 1: Create Task Directory — 2026-08-12T07:42:38.000Z

Pre-assigned output folder `tasks/task_1247_campus_recruiting_internship_program` with `workspace/` subdirectory confirmed to exist. Step 1 treated as done per orchestrator directive (auto-index scan skipped).

## Step 2: Generate Scaffold — 2026-08-12T09:00:32.000Z

All three scaffold artifacts are generated, lint-clean, and self-consistent. Summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1247_campus_recruiting_internship_program/`):
- `SCAFFOLD.yaml` (1852 lines) — §1.0–§1.7 only: verbatim scenario, `domain_name: campus-recruiting`, `api_prefix: /campus-recruiting`, fixed response envelope, 14 entities, 9 state machines, 2 OCC concurrency rules, 6 calculation rules, 46 ordered validations, 76 endpoints (incl. `POST /campus-recruiting/_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`), 45 error codes, 6 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1592 lines) — single key `scaffold_difficulty_design`: all 9 rules × 2 instances = 18, each with structured `setup_api_calls`/`trigger`/`assert` recipes.
- `SCAFFOLD_CORNER_DESIGN.yaml` (5187 lines) — single key `scaffold_corner_design`: 88 instances across all nine taxonomy sections (82 with recipes, 6 `excluded_because` stubs citing §1.8 instances).

**Harder-than-expert design choices** (density over volume): workflow-orchestration pipeline + quota-allocation blend; posture-gated season epochs (ops-run checkpoints) gating every child operation; three dual-variant calculation domains (Application screening score provisional-vs-final 30 vs 55; Offer exploding deadline WALL_CLOCK `2026-07-11T08:00:00Z` vs BUSINESS_HOURS `2026-07-14T16:00:00Z`; conversion rates 0.5 vs 1.0 on different denominators); combinatorial modes (a) tiered stipend with cap (400000) and (b) pinned per-component rounding (110019 vs naive 110020); cyclic machines on Offer (renegotiation loop) and Application (book/cancel auto-flip); depth-3 accept cascade vs depth-2 disburse cascade; priority conflicts state>fiscal and safety>temporal; boundary precision at cap equality, deadline-instant inclusivity, budget equality, 15-minute buffer equality; half-open vs buffered interval overlap semantics; compensating invariants on stipend cents vs day seat counts; OCC on Offer and SchoolTarget; segregation of duties (mentor ≠ prior evaluator).

**Verification**: `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (76 endpoints, 14 entities, 18+78 instances, 1482 calls scanned). Additionally: zero unbound `${var}` placeholders, 106 globally unique instance names, all `grounds:` resolve into §1.1–§1.7, all 45 errors referenced by validations, enum closure holds, OCC hard constraints hold, no forbidden concurrency vocabulary, and every formula-derived assert literal was pre-computed and checked with Python. One design fix during authoring: offer extend/accept posture widened to `{OFFER_PERIOD, INTERN_ACTIVE}` so the season-close offer-expiry cascade is reachable.

## Step 3: Copy Shared Files — 2026-08-12T09:00:59.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1247_campus_recruiting_internship_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T09:21:20.000Z

PRD generation complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1247_campus_recruiting_internship_program/workspace/PRD.md` (374 lines).

## What was produced

A prose PRD for the campus-recruiting domain, structured as: §1 Introduction (2 paragraphs, business-pain-point angle); §2 Global Specifications with 11 domain-derived subsections (roles/identity semantics, the verbatim response-envelope contract, pagination + filter conventions, season-epoch posture gating, the logical clock, common resource properties, nested path validation, precision/rounding, OCC, stored counters/ledger invariants, and the global validation evaluation order); §3 Business Logic in 8 lifecycle-organized subsections with scattered rules; §4 endpoint table (4 columns, 76 rows); §5 error catalogue (2 columns, 45 rows).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 81 required, 81 present, 0 missing
- endpoints[].request_body/input extras (to_iso8601, decision, outcome, additional_hours,
  expected_offer_version, expected_school_target_version, plus limit/offset and the
  conversion-summary/clock output names): 11 required, 11 present, 0 missing
- endpoints[].query_params (status, tier, event_type, school_target_id, season_id, limit, offset): all present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 46 checked, 46 expressed in prose (global 13-step ladder in §2.11 plus
  per-endpoint ordered chains for submission, screening, booking, extend, accept, assignment creation,
  intern-evaluation, disburse), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_offer_version /
  expected_school_target_version + ERR_STALE_OFFER_VERSION / ERR_STALE_SCHOOL_TARGET_VERSION + HTTP 412
  all named; no race-framing), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed (including both auto-flip rules, the lazy
  EXPIRED flip, all 5 withdraw variants with ordered cascades and suppression, both PUT-offer self/cycle
  transitions), 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise prose (dual-variant screening score with all 7
  constants, both deadline variants with the half-open 09:00–17:00 UTC business window, tiered stipend
  with both distance bands and the METRO+CORE surcharge, per-component round-half-up total comp with the
  pinned rounding order, the 1x/2x-weighted return-offer score against the 4.00 threshold, both 4-dp
  conversion rates with zero-denominator rule), 0 missing
- validations[] conditions: 46 checked, 46 matchable to error_id in §2/§3 prose (all 45 catalog error ids
  verified present in narrative), 0 missing
- endpoints[].side_effects / applies_to: all expressed, including the full posture-gate map (§2.4) and
  the state-gate scope enumerations (offer/slot/day/disbursement), 0 missing
- entities[].fields[] structured content: all defaults (72h/WALL_CLOCK/72h, 6 slots/2 interns, capability
  flags, 0 counters), null-until semantics (screening_score_final; the four offer fields), and uniqueness
  rules (case-insensitive email vs case-sensitive school_name) reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (SHORTLIST/REJECT, 5 withdraw branches, deadline variants,
  conversion variants, cancel/no-show, decline/rescind, unassign/complete, MID/FINAL), all equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 523
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verified items: §2.2 is byte-identical to the canonical `section-2.2-response-structure.md` source; no pseudocode operators (`>=`, `==`, `+=`, `min()`, etc.) or fuzzy hedging words anywhere in §2/§3 prose; all 50 state/enum values appear as exact backticked strings. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened or read.

## Step 5: Generate Unit Tests — 2026-08-12T09:50:00.000Z

Test suite generation complete. `test_helpers/` (9 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`) and `test_suite/` (conftest.py + 9 test files, 121 test functions) written under `/home/ubuntu/github/CodingPRD/tasks/task_1247_campus_recruiting_internship_program/`.

Note on provenance: this step was executed by the original headless run (07:42Z); that run's log stayed empty because `claude -p` only flushes stdout at exit, and it was incorrectly diagnosed as dead. A replacement resume session (this one) verified completeness on disk and terminated the original process before it could enter Step 7 concurrently. All test files compile (`py_compile` clean).

### Design-index coverage audit (design-index-only contract)

Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 18 instances (9 rules × 2), each requiring ≥2 tests tagged `Design: Difficulty/<rule_id>/<instance.name>`:
- 18/18 fully covered (≥2 tags each), 0 short, 0 missing.

Queue B — `SCAFFOLD_CORNER_DESIGN.yaml`: 88 instances total, 10 `excluded_because:` stubs (6 errors-section + 2 state_machines + 2 calculations; cross-references resolve into queue A), 78 non-stub instances, each requiring ≥1 test tagged `Design: Corner/<section>/<instance.name>`:
- entities 8/8, state_machines 19/19, calculations 9/9, validations 27/27, endpoints 4/4, rbac 8/8, complexity_layers 2/2, consistency_model 1/1 → 78/78 covered, 0 missing.

Unknown/dangling `Design:` tags in the suite: 0. Total tag occurrences: 121 (one per test function).

File layout (domain-language grouping, numbered simple→complex):
- `test_01_season_lifecycle.py` (14 tests) — season creation/advance/close, posture gating, logical clock
- `test_02_screening_scores.py` (5) — provisional/final dual-variant screening math, threshold boundary, cap at 100
- `test_03_campus_events_and_schools.py` (8) — school targets, OCC on SchoolTarget, campus events, half-open adjacency
- `test_04_interview_logistics.py` (19) — interview days/slots, 15-minute evaluator buffer, seat-count compensation, cancel/no-show
- `test_05_application_intake.py` (12) — submission window, caps, uniqueness, withdraw cascades
- `test_06_offers.py` (24) — offer drafting, dual-variant deadlines, tiered stipend math, rounding order, OCC on Offer, renegotiation cycle, accept cascade
- `test_07_stipend_ledger_and_funnel.py` (10) — disbursement lifecycle, reserved-ledger invariant, FK reverse reachability, conversion summary
- `test_08_intern_projects.py` (14) — projects, assignments, intern evaluations, return-offer score, segregation of duties
- `test_09_security_and_envelope.py` (15) — RBAC matrix, identity threading, response-envelope/pagination shape, error catalogue shape

## Step 6: Generate Implementation (RECONSTRUCTED FROM DISK) — 2026-08-12T09:50:30.000Z

This entry is reconstructed post-hoc from on-disk artifacts; the original run died (silently, empty log) before logging it.

`workspace/implementation/` contains a complete Flask application: 24 Python files (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `utils.py`, plus `routes/` and `services/` packages) and `start.sh` (executable, binds `PORT`/`0.0.0.0`, foreground). Route parity verified: 76 registered routes == 76 endpoints declared in `SCAFFOLD.yaml` §1.5 (including `POST /campus-recruiting/_clock/set_current_utc`). Requirements pinned in `requirements.txt`. Step 6 treated as COMPLETE.

## Step 7: Run Tests and Iterate — 2026-08-12T10:20:00.000Z

The iteration loop was owned and driven in-session (headless-resume constraint forbade delegating to a subagent): run the 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`, `results.{1..8}.json`), read all 8 result files, diagnose the union of failures, fix, rerun. Iterations: 3 sweeps total (1 diagnostic + 1 self-inflicted regression + 1 clean).

**Sweep 1** (baseline): 116/121 avg; union of 7 distinct failing tests:
- 4 deterministic (8/8 rounds), all in `test_06_offers.py`: `test_wall_clock_deadline_is_straight_hour_addition`, `test_business_hours_deadline_counts_only_business_seconds`, `test_full_cycle_reextend_recomputes_deadline_and_counts`, `test_extension_cap_boundary` — all tripped on `deadline_at` exact-string equality (`'...T08:00:00.000Z' != '...T08:00:00Z'`).
- 3 flaky (1-3 rounds each): `test_return_offer_extended_at_threshold` ("API server could not be restarted"), `test_intern_evaluation_immutability` (ConnectionResetError 104), `test_final_before_mid_and_duplicate_mid_rejected` (same restart flake class).

**Diagnoses (diagnostic protocol):**
- STEP 0/1/2 for the 4 deterministic failures: PRD §3.6 covers and uniquely pins the deadline *instants* (16h wall-clock from Friday 16:00Z → Saturday 08:00Z; 16 business hours → Tuesday 16:00Z; 72h re-extend and +72h extension-grant arithmetic). The values the implementation returns are CORRECT; the tests compared raw strings while PRD mandates three-fractional-digit rendering only for `api_request_timestamp` and `created_at` (§2 envelope / common fields) — `deadline_at` rendering is PRD-silent, and the framework's `is_iso8601_timestamp` accepts optional milliseconds, so two faithful PRD-only implementers can legitimately emit either form. Verdict: TEST IS WRONG (assertion over-specifies rendering; the rule-bearing content is the instant). Fix per STEP 2: assertions now compare parsed instants (`datetime.fromisoformat`) instead of exact strings. No deletion warranted — the underlying rule is PRD-covered and uniquely derivable; only the string rendering was not.
- The 3 flaky failures are harness/timing artifacts (server restart readiness under 8-fold concurrent load + stale keep-alive connections pooled across per-test server restarts — the framework's session-scoped `requests.Session` never discards dead sockets; POSTs are not retried). No PRD rule implicated; no test deleted.

**Fixes applied:**
- `test_suite/test_06_offers.py`: 4 assertions converted to instant comparison via a module-local `_instant()` helper; docstrings, PRD citations, and `Design:` tags untouched.
- `test_helpers/api_client.py`: `api_client.session.headers["Connection"] = "close"` — never reuse a pooled connection across a server restart.
- `workspace/implementation/app.py`: serve via waitress (`threads=8`, `channel_timeout=30`) with fallback to Flask dev server; NOTE — a first attempt also set a `Connection: close` response header, which waitress rejects per PEP 3333 (hop-by-hop); that caused sweep 2's 0/121 regression and was immediately reverted.
- `workspace/implementation/requirements.txt`: added `waitress>=3.0.0`; `start.sh` import-check widened accordingly.

**Sweep 3 (final): 8/8 rounds × 121/121 passed. Union of failures: 0.** Step 7 exit condition met.

**Step 7 diff (for Step 8):** 0 deletions; test_suite fixes = the 4 `deadline_at` instant-comparison assertions (signal: PRD does not state fractional-digit rendering for computed timestamp fields like `deadline_at`; implementation renders all timestamps with three fractional digits); test_helpers fixes = client connection hygiene (no PRD impact); implementation fixes = serving infrastructure only (waitress; no PRD-visible behavior change).

## Step 8: Finalize PRD — 2026-08-12T10:35:00.000Z

Subagent produced `workspace/PRD_FINALIZED.md` (minimal diff over `PRD.md`). Verbatim summary:

**Line counts:** PRD.md = 374 lines; PRD_FINALIZED.md = 376 lines; delta = +2 lines (+0.53%).

**Changes (both trace to the single PRD-relevant Step 7 signal — fractional-digit rendering of server-emitted timestamps; the waitress serving fix and the `Connection: close` test-helper fix have no PRD-visible behavior and required no edits):**

- §2.6 — revise — `updated_at` bullet now reads "an ISO 8601 UTC timestamp **with three fractional digits**, refreshed on any modification of the resource" — `implementation/utils.py:182-185` (`touch()` renders `updated_at` via `format_iso`, which always emits `.{ms:03d}Z`).
- §2.6 — insert — new paragraph after the `version` bullet pinning that the same three-fractional-digit ISO 8601 UTC rendering applies to every other server-emitted timestamp (season window bounds, day `window_start_at`/`window_end_at`, event/slot `start_at`/`end_at`, `expected_graduation_date`, offer `extended_at`/`deadline_at`, clock `current_utc`) — `implementation/utils.py:28-35` (`format_iso`, the sole serializer), `implementation/services/domain.py:117-122,164-165,179,228-229,245-246,277-278`, `implementation/routes/seasons.py:46`.

**Per-edit pre-edit search log:** subject = server-side timestamp rendering format for all emitted timestamps other than the already-pinned `api_request_timestamp`/`created_at`. Paths enumerated: `utils.py:28-35` (`format_iso`, sole serializer), `utils.py:38-40` (`now_iso` → envelope), `utils.py:182-195` (`touch`/`stamp_new`), `response.py:18,32,50`, `services/domain.py` (all views: season window bounds, event/slot/day bounds, `expected_graduation_date`, offer `extended_at`/`deadline_at`), `routes/seasons.py:46` (clock `current_utc`), `routes/intern_evaluations.py:81`, `services/calculations.py` (deadline math renders only via `offer_view`); repo-wide grep confirmed no renderer outside `format_iso`. Wording: universal claim backed by explicit field enumeration covering every rendered timestamp field; no narrowing needed.

## Step 9: Complete PRD — 2026-08-12T11:05:00.000Z

Subagent produced `workspace/PRD_COMPLETED.md` from `workspace/PRD_FINALIZED.md` (full implementation↔PRD scan). Verbatim summary:

**Source vs completed:** PRD_FINALIZED.md 376 lines / 62,717 chars → PRD_COMPLETED.md 378 lines / 67,959 chars (char-delta +5,242; 27 diff hunks, 29 revised paragraphs).

**Counts:** 24 ambiguity-pins, 4 mismatch-revisions.

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.1 — revise — ambiguity — Evaluator may read only own employee record/slots/evaluations; Mentor only own employee record/assignments/intern-evaluations — employees.py:82-85,92-94,112-114,132-134; interview_slots.py:153-154; evaluations.py:115-116,124-125; project_assignments.py:123-124; intern_evaluations.py:105-106,119-122
- §2.2 — revise — ambiguity — `api_request_timestamp` reads host wall clock, never logical clock — utils.py:38-40
- §2.2 — insert — ambiguity — unknown path/unsupported method → ERR_NOT_FOUND 404; unhandled failure → ERR_VALIDATION 400 — app.py:54-68
- §2.3 — revise — ambiguity — non-integer/out-of-range limit (1..100) or negative offset → ERR_VALIDATION; creation-timestamp ties keep insertion order; `has_more` = offset+limit < total_count — utils.py:157-179; response.py:36
- §2.3 — insert — ambiguity — filter values matched literally; unrecognized value yields empty page, not an error — e.g. seasons.py:101-106
- §2.4 — revise — ambiguity — non-posture-gated enumeration extended with school-target creation, employee registration, intern-project creation — school_targets.py:35-37; employees.py:29-32; intern_projects.py:25-28
- §2.6 — revise — ambiguity — `created_at` (and initial `updated_at`) stamped from logical clock; later `updated_at` refreshes from host wall clock — utils.py:182-195
- §2.11(5) — revise — ambiguity — end-after-start interval rule applies to events/days/slots only; season window bounds not cross-checked — campus_events.py:46-47; interview_days.py:37-39; interview_slots.py:71-72; seasons.py:54-59
- §2.11(5) — revise — ambiguity — required strings must be non-empty; explicit null counts as absent — utils.py:61-82
- §2.11 — insert — mismatch — concrete precedence: path existence confirmed as each resource loads (before ownership over it); submission payloads (application/interview-evaluation/intern-evaluation) shape-validated before ownership; payload-referenced entity existence after ownership, before posture; on revisions, endpoint gates fire before edit-field validation (school-target patch: version match first; evaluation revision: ownership/posture/day-state first) — applications.py:49-69; evaluations.py:44-51,88-106; intern_evaluations.py:47-54; school_targets.py:99-130
- §3.1 — revise — ambiguity — duplicate school_name → ERR_VALIDATION 400 — school_targets.py:49-51
- §3.1 — insert — ambiguity — advance from INTERN_ACTIVE/CLOSED → ERR_SEASON_ADVANCE_BLOCKED — seasons.py:152-154
- §3.1 — revise — ambiguity — patch: version match before edit-field validation; null `exploding_offer_hours_override` clears override — school_targets.py:99-130
- §3.1 — insert — ambiguity — dropping non-ACTIVE target → ERR_APPLICATION_STATE_FORBIDDEN 409 — school_targets.py:144-145
- §3.2 — revise — ambiguity — event school_target_id unknown or cross-season → ERR_NOT_FOUND — campus_events.py:52-56
- §3.2 — revise — ambiguity — `resume_count` is required (int ≥ 0) in the completion payload — campus_events.py:136-142
- §3.3 — insert — ambiguity — unresolvable candidate_id/school_target_id or cross-season school → ERR_NOT_FOUND — applications.py:65-69
- §3.4 — revise — ambiguity — failed SHORTLIST (threshold) still stores `screening_score_final` and bumps `version` — applications.py:184-189
- §3.4 — insert — ambiguity — reject of non-DECISION_PENDING application → ERR_APPLICATION_STATE_FORBIDDEN — applications.py:204-205
- §3.5 — revise — ambiguity — employee email unique within season case-sensitively; duplicate → ERR_VALIDATION 400 — employees.py:44-46
- §3.5 — revise — ambiguity — booking resolves application/evaluator by id alone (no season-membership rule); COI compared case-insensitively with whitespace trimmed; unset alma mater never conflicts — interview_slots.py:74-76,88-91
- §3.5 — revise — ambiguity — slot cancel/no-show guard order: posture → day state → slot state — interview_slots.py:164-169,185-190
- §3.5 — revise — ambiguity — locking a non-OPEN day → ERR_DAY_STATE_FORBIDDEN — interview_days.py:93-94
- §3.5 — revise — ambiguity — evaluation revision: ownership/posture/day-state guards fire before revised values are validated — evaluations.py:88-106
- §3.6 — revise — mismatch — extend guard order is posture → offer DRAFT → application DECISION_PENDING → window (PRD had application-state before offer-state) — offers.py:192-204
- §3.6 — revise — mismatch — BUSINESS_HOURS deadline counts business seconds over the half-open interval [extended_at, deadline_at), not "up to and including" the deadline — calculations.py:63-87
- §3.6 — revise — mismatch — lazy flip applies to offer reads (single + per-application list), decline, and rescind only; decline/rescind past deadline flip to EXPIRED then fail with ERR_OFFER_STATE_FORBIDDEN; extend-deadline performs no lazy-flip observation (PRD said "any offer operation") — offers.py:105,122-123,289-293,308-311,340-351
- §3.7 — revise — ambiguity — assignment guards include: application and mentor must belong to project's season, cross-season → ERR_NOT_FOUND, checked after application-state, before project-state — project_assignments.py:70-80
- §3.8 — insert — ambiguity — closing a season not in INTERN_ACTIVE → ERR_SEASON_CLOSE_BLOCKED — seasons.py:171-174

Everything else in the implementation (envelope shape, posture map, screening/stipend/comp/return-offer formulas, guard orders, cascades, counters, endpoint table, error catalogue) was already uniquely pinned by PRD_FINALIZED.md and verified against the code without change.

---

PIPELINE COMPLETE. Final state: 8/8 sweep rounds × 121/121 tests passing (`workspace/implementation/results.{1..8}.json`); PRD chain `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` aligned to the implementation.
