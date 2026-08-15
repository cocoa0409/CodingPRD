# Worklog — task_1720_utilization_review_medical_necessity

## Step 1: Create Task Directory — 2026-08-14T10:53:00.000Z

Pre-created and pre-assigned: `tasks/task_1720_utilization_review_medical_necessity/` with `workspace/` subdirectory. Verified present; treated as DONE per pipeline instructions.

## Step 2: Generate Scaffold — 2026-08-14T11:44:00.000Z

## Task 1720 — Utilization Review & Medical Necessity: scaffold complete

**Output files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1720_utilization_review_medical_necessity/`):
- `SCAFFOLD.yaml` (§1.0–§1.7 only — no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

**Counts**

| Element | Count |
|---|---|
| Entities (§1.1) | 13 |
| State machines (§1.2) | 10 |
| Concurrency rules (§1.2.1, OCC) | 2 |
| Calculations (§1.3) | 6 |
| Validations (§1.4) | 27 |
| Endpoints (§1.5) | 52 |
| Errors (§1.6) | 27 |
| Roles (§1.7) | 7 |
| Difficulty instances (§1.8) | 21 (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear 3, cascade 2, priority-pair 2, boundary 2, cross-entity 3, temporal-overlap 2, invariant 2) |
| Corner instances (§1.9) | 56 total: 52 active + 4 `excluded_because` stubs, across all 9 claim-guide sections |

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (553 calls scanned; 0 violations). Supplementary self-checks: every error referenced by a validation, no forbidden race vocabulary, all 77 instance names unique, all `grounds:` refs resolve, all numeric asserts pre-computed (necessity scores 98/72/60/52; rebill 77000 vs 77001 trap; deadlines 2026-08-05T12:00:00Z = +72h and 2026-10-01T12:00:00Z = +60d).

**Design decisions worth recording in the worklog**
1. **Archetype**: compliance/audit (primary) × workflow orchestration (secondary); `segregation_of_duties` role model (attending barred from CC44 committee/advisor review of own cases); 4 layers: OCC, cascading side effects, rate/threshold triggers, scheduled actions.
2. **UtilizationCase carries two independent state axes** (review_status × auth_status) — the Rule-3 parallel machine; AuthorizationRequest adds the PENDED→SUBMITTED cycle with `submission_round`; CC44 adds fork-join + RESCIND revert.
3. **Two OCC rules** on `UtilizationCase.version` guard the create-with-supersede writers (authorization requests, CC44 requests); every recipe re-reads the case to capture a fresh version before OCC calls.
4. **Logical clock** `POST /_clock/set_current_utc` with mandatory startup default `2026-08-01T00:00:00Z`; P2P `EXPIRED` and denial `CLOSED_NO_APPEAL` materialize lazily on reads/writes after their deadlines (keeps tests deterministic; appeal-create evaluates the deadline directly so ERR_APPEAL_DEADLINE_PASSED wins over lazy materialization).
5. **Two distinct interval semantics for Rule 8**: advisor calendar (minute-granularity, 15-minute clearance buffer, exactly-15 gap allowed) vs case certified-day axis (half-open day intervals, adjacency allowed, overlap rejected).
6. **Validation priority fix during replay**: ERR_DENIAL_NOT_FINAL (p11, scheduled-P2P conflict) and ERR_APPEAL_ALREADY_FILED (p23, prior appeal exists) were reworded so neither shadows the other.
7. **Replay-discovered precondition added**: a new ConcurrentReview cannot be created while a previous one is still SUBMITTED on the same auth (keeps the cadence anchor computable).
8. **Endpoint count (52) exceeds the Expert band (20–32)** deliberately: ~15 are FK reverse-reachability GETs mandated by lint check (f), and the scenario's 8 workflow surfaces are each exercised; coupling density (not volume) is the difficulty driver. All placeholders in §1.5 paths are `{id}` because the linter's sub-resource match is literal.

## Step 3: Copy Shared Files — 2026-08-14T11:45:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1720_utilization_review_medical_necessity/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T12:02:00.000Z

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1720_utilization_review_medical_necessity/workspace/PRD.md`

### PRD section list
- **1. Introduction** — 2 paragraphs (business context + system scope)
- **2. Global Specifications & System-Wide Principles** (12 subsections): 2.1 RBAC with per-role identity translation; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Case Identity, Dual Lifecycle Axes & Hierarchical Consistency; 2.5 Validation Order (27-rule priority pipeline compressed into 11 ordered stages); 2.6 Common Resource Properties (with the AuditEvent no-`updated_at`/no-`version` exception); 2.7 Monetary Values, Rounding & Integer Arithmetic; 2.8 The Two-Midnight Benchmark (PROVISIONAL/FINAL variants); 2.9 Certified Day Intervals & Bed-Day Budget; 2.10 OCC; 2.11 The Logical Clock; 2.12 Nested Resource Retrieval
- **3. Business Logic & Workflows** (10 subsections, organized chronologically along the stay lifecycle): payer/physician configuration → case opening & admission review → authorization requests → concurrent reviews → peer-to-peer conferences → condition code 44 → avoidable days & escalation → denials & appeals → discharge → audit trail
- **4. Endpoint Definitions** — 51-row, 4-column table
- **5. Error Code Catalogue** — 27-row, 2-column table

### Approximate line count
326 lines.

### Harder-to-render scaffold elements
1. **The dual-axis `UtilizationCase` state machine** (`review_status` × `auth_status` with independent transitions) — required careful prose so readers don't collapse it into one status field; handled with an explicit "always evaluate both fields" passage in §2.4.
2. **The escalation credit circular dependency** (eligibility depends on raw tier, effective tier depends on credits) — rendered as a pinned five-step evaluation-order narrative in §3.7.
3. **The `cc44_rebill_estimate` pinned rounding order** — rendered as an explicit "documented trap variant" rejection in §2.7 plus the formula walk-through in §3.6.
4. **The two-midnight PROVISIONAL/FINAL variant divergence** — split between §2.8 (mechanism) and §3.2/§3.9 (trigger points), since a single concentrated block would have made the discharge cascade too dense.
5. **`ERR_VALIDATION_FAILED` shape-integrity details** (P2P 15-minute duration floor, computed-field rejection) — these live in §2.5 rather than §3, since they're cross-cutting.

### Zero-Silence Rule notes (deliberate compression/scattering)
- **§2.5 Validation Order compresses the scaffold's 27 priority rows into 11 numbered stages.** Every stage names its error IDs explicitly (all 27 appear), but individual priorities 9–17 (the domain state/safety/temporal gates) are grouped into one stage with all nine error IDs listed inline, and priorities 18–23 (business constraints) into another. Relative order within each group is preserved by list order, and the "earliest gate wins" rule is stated explicitly so a reader can reconstruct the full ordering.
- **Request-body parameters are scattered per the spec:** `decision` appears in four separate workflow subsections (§3.3 payer decision, §3.4 concurrent decision, §3.6 concurrence/committee `decision` values, §3.8 appeal decision); `certified_day_start`/`certified_day_count` appear in §3.3 (approval grant) and again in §3.5 (frontier-append on P2P overturn); `outcome`/`overturned_day_count` in §3.5 and §3.8.
- **OCC `expected_case_version`** is stated once as the mechanism in §2.10, then re-invoked at each guarded writer (§3.3 authorization create, §3.6 CC44 initiate) — no third restatement in §2.
- **Audit event type names** are scattered adjacent to the transition that fires them rather than catalogued; the full set is recapped at a category level in §3.10.
- **Filter query params** (`plan_class`, `is_advisor`, `payer_id`, `attending_physician_id`, `review_status`, `auth_status`, `status`) are named in the §3 narrative of the resource they filter, not in §4.

### Hard Contract Reports
```
Field coverage check:
- entities[].fields + endpoints input/query/path params: 105 required, 105 present, 0 missing
Status: PASS

Rule coverage check:
- validation priority ordering: expressed (§2.5, 11-stage ordered pipeline)
- concurrency_rules OCC rejections: 2 checked, 2 expressed (write-endpoint + expected_case_version + ERR_STALE_VERSION/412)
- state-machine transitions: all from/to states, preconditions, error IDs, side effects expressed
- calculations: 6/6 fully expressed in precise prose (no pseudocode, no fuzzy words — verified by scan)
- validations: 27/27 matchable to error IDs in §2/§3 prose
- endpoint side effects / applies_to scopes: expressed (spot-audited, 45/45 checks pass)
- field-level structured content (defaults, initial values, computed semantics): reconstructible
- sibling-branch symmetry: appeal UPHELD/OVERTURNED/PARTIAL rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 536
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-14T12:36:00.000Z

**Output locations**
- `/home/ubuntu/github/CodingPRD/tasks/task_1720_utilization_review_medical_necessity/test_helpers/` — `__init__.py` (barrel), `types.py` (13 entity TypedDicts — AuditEvent correctly omits `updated_at`/`version` per PRD §2.6 — plus 20 status/role enums), `api_client.py` (52 methods, one per PRD §4 endpoint including `/_clock/set_current_utc`), `api_errors.py` (27 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py` (14 per-entity structural assertions + certified-counter invariant), `factories.py` (25 payload factories, input fields only), `constants.py` (score caps/weights, tier thresholds 2/4/6, 50-char gate, 15-min P2P constants, canonical timeline literals), `test_users.py` (7 roles; per-instance builders for entity-backed `AttendingPhysician`/`PhysicianAdvisor`), `fixtures.py` (5-tier composites: `setup_case`, `setup_case_with_submitted_review`, `setup_submitted_auth`/`setup_approved_auth`/`setup_denied_auth`/`setup_p2p_scheduled`/`setup_appeal_filed`, `setup_cc44_open`/`setup_cc44_committee_pending`, `setup_avoidable_days`).
- `/home/ubuntu/github/CodingPRD/tasks/task_1720_utilization_review_medical_necessity/test_suite/` — `conftest.py` + 9 files: `test_01_envelope_and_security`, `test_02_case_opening_and_admission_review`, `test_03_authorization_lifecycle`, `test_04_concurrent_reviews`, `test_05_peer_to_peer`, `test_06_condition_code_44`, `test_07_avoidable_days_escalations`, `test_08_denials_appeals`, `test_09_discharge`.

**Test counts**
- Queue A (Difficulty): 42 tests — all 21 instances × exactly 2 tests each.
- Queue B (Corner): 52 tests — all 52 non-stub instances × 1 test each.
- Total: 94 tests, all collected by pytest cleanly (`--collect-only` verified).

**Instances skipped**: none. All 52 non-stub corner instances and all 21 difficulty instances passed the PRD-first two-condition filter. The 4 `excluded_because` stubs (`necessity_score_boundary_values`, `two_midnight_boundary_exactly_two`, `avoidable_attribution_variants`, `denial_not_final_error_covered`) were not translated; all four cross-references resolve to real difficulty instances.

**Stage 2 self-check findings**
- Design-tag audit: every test has exactly one `Design:` tag; all 94 tags resolve to real instances; coverage thresholds met; no skip/xfail markers anywhere.
- PRD citation sweep: all 94 docstrings carry quotes with a ≥8-word contiguous run verified verbatim against PRD.md.
- No "scaffold"/table references in generated code comments.
- Three derivability adjustments vs. literal recipe text (recipe intent preserved): (1) dropped `version == 1` assertions from `physician_is_advisor_defaults_false` and `utilization_case_create_computed_and_system_fields` — the PRD pins "increments by exactly 1" but never the initial value, so tests assert int type / relative +1; (2) the two attribution-variant tests stagger the logical clock between same-day barrier creates so FIRST_CAUSE's "earliest created" owner is deterministic whether an implementer reads `created_at` from wall or logical clock; (3) `appeal_after_deadline_passed` was kept (not skipped) because PRD §3.8 scopes lazy `CLOSED_NO_APPEAL` materialization explicitly to reads, making `ERR_APPEAL_DEADLINE_PASSED` uniquely derivable for a filing attempt.

## Step 6: Generate Implementation — 2026-08-14T12:36:00.000Z

**Task**: `task_1720_utilization_review_medical_necessity` — Utilization Review & Medical Necessity API.

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1720_utilization_review_medical_necessity/workspace/implementation/`)
- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"` so per-test reboots are cheap; `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask app, blueprint registration, ApiError/404/405/400/500 error handlers
- `db.py` — in-memory dict stores (13 entity maps), all empty at boot; UUID + logical-clock timestamp helpers
- `errors.py` — all 27 error IDs from the scaffold catalog
- `response.py` — envelope helpers producing the exact scaffold shape (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta for lists only)
- `middleware.py` — X-User-ID/X-User-Role auth (7 roles), role-authorization, attending-ownership check
- `routes/` — `payers.py`, `physicians.py`, `cases.py`, `admission_reviews.py`, `authorization_requests.py`, `concurrent_reviews.py`, `p2p.py`, `cc44.py`, `avoidable_days.py`, `escalations.py`, `denials.py`, `appeals.py`, `audit.py`, `clock.py`, `helpers.py`
- `services/` — `clock.py` (logical clock, default 2026-08-01T00:00:00Z, never wall-clock), `calculations.py`, `case_service.py` (certified intervals, attribution, escalation tiers, lazy EXPIRED/CLOSED_NO_APPEAL), `common.py`, `validation.py`

### Endpoints implemented: 43/43 from the endpoint table (all routes in PRD §4 including `POST /_clock/set_current_utc`)

### State machines implemented (9): UtilizationCase dual-axis (review_status × auth_status with independent transitions), AdmissionReview (DRAFT→SUBMITTED→ADVISOR_REVIEWED), AuthorizationRequest (SUBMITTED/PENDED cycle, APPROVED, DENIED, WITHDRAWN, SUPERSEDED incl. DENIED→APPROVED overturn), ConcurrentReview, PeerToPeerConference (incl. lazy EXPIRED materialization and reschedule self-loop with cap 2), ConditionCode44Request (6-state with concurrence/committee/rescind), AvoidableDay, EscalationCase, DenialCase (incl. lazy CLOSED_NO_APPEAL), AppealCase.

### Calculations implemented (6): `medical_necessity_score` (caps 12/12/3, weights 5/5, comorbidity 4 for Medicare family vs 2, cap 100, threshold 60 — integer math), `two_midnight_benchmark` (calendar-date diff, PROVISIONAL vs FINAL variants, ≥2 MET), `cc44_rebill_estimate` (pinned per-line Decimal ROUND_HALF_UP then sum; sum-then-round trap avoided), `avoidable_day_attribution` (FIRST_CAUSE chronological vs DOMINANT_CAUSE weighted, tie-breaks on created_at then barrier_code, never id), `concurrent_review_cadence_schedule` (anchor = auth approval decided_at or previous review decided_at + cadence hours; overdue check with equality allowed), `escalation_tier_resolution` (raw tiers 2/4/6, pinned credit-eligibility-on-raw-tier evaluation order, net-count effective_tier floored at 0, create/upgrade-only escalation semantics).

### Validation pipeline (priorities 1–27 enforced in order)
1. Auth headers → ERR_UNAUTHENTICATED (401) → 2. Role listed → ERR_FORBIDDEN_ROLE (403) → 3. Request shape (required fields, enums, ranges, P2P 15-min duration/end-after-start, system-field rejection) → ERR_VALIDATION_FAILED (400) → 4. Path existence left-to-right → ERR_NOT_FOUND (404) → 5. Attending ownership → ERR_NOT_CASE_ATTENDING (403) → 6. Case-open gate → ERR_CASE_CLOSED (409) → 7. State-machine legality → ERR_INVALID_STATE (409) → 8. OCC `expected_case_version` → ERR_STALE_VERSION (412) → 9–17. Domain gates (ERR_CC44_POST_DISCHARGE, ERR_P2P_NOT_ELIGIBLE, ERR_DENIAL_NOT_FINAL, ERR_CLINICAL_DOC_INCOMPLETE ≥50 chars, ERR_SOD_ROLE_CONFLICT, ERR_TWO_MIDNIGHT_DOC_REQUIRED, temporal: ERR_P2P_WINDOW_EXPIRED/ERR_REVIEW_OVERDUE/ERR_APPEAL_DEADLINE_PASSED) → 18–23. Business constraints (CC44 single-open, avoidable-day uniqueness, advisor calendar 15-min buffered clearance, certified-interval half-open overlap with adjacency allowed, P2P reschedule cap, one-appeal-per-denial) → 24–27. Referential/fiscal (Medicare-family CC44 eligibility, CC44 clinical basis vs latest review, is_advisor reference, bed-day budget on create and all approvals).

### Boot verification (smoke-tested)
Launched via `bash start.sh` on a fresh port: store boots empty (`GET /api/payers` → `data: []`), logical clock defaults to `2026-08-01T00:00:00Z`, 401 envelope exact. A full end-to-end workflow test passed: payer/physician setup → case open → admission review submit (score 100, CRITERIA_MET) → auth request with OCC + stale-version rejection → approve with interval [1,4) → concurrent review + approval → supersede + deny → DenialCase → P2P schedule (attending ownership 403 verified) → denial P2P_SCHEDULED → appeal blocked with ERR_DENIAL_NOT_FINAL → P2P complete OVERTURNED with frontier restoration → avoidable days + duplicate rejection + escalation auto-create at tier 1 → audit trail (11 events, append-only shape without updated_at/version) → discharge cascade (FINAL benchmark NOT_MET, WITHDRAWN/RESOLVED cascades, repeat discharge → ERR_INVALID_STATE, closed-case child creation → ERR_CASE_CLOSED, CC44 post-discharge → ERR_CC44_POST_DISCHARGE) → CC44 full cycle on a second case (per-line rebill 38.5→39+39=78 cents, concurrence, SoD 422, committee approve flipping status to OBSERVATION, rescind restoring INPATIENT). Server killed; ports free; no seeding code anywhere.

## Step 7: Test-Fix Iteration — 2026-08-14T13:05:00Z

### Iteration 1 sweep (baseline): 81/94 passed in each of 8 parallel rounds; identical 13-test failure set in every round (deterministic, not flaky).

Failure union (13 tests) diagnosed in 5 clusters:

**Cluster A — computed-deadline timestamp rendering (7 tests: test_04 review_due_at x2 tests, test_05 window_deadline_at/appeal_deadline_at x5 tests).**
STEP 1a: the instant rule is verbatim in PRD (§3.3 appeal_deadline_at = denied_at + appeal_deadline_days; §3.4 review_due_at = anchor + cadence; §3.5 window_deadline_at = decided_at + p2p_window_hours). STEP 1b: the byte-exact string rendering is NOT uniquely derivable — PRD pins "three fractional digits" only for created_at/updated_at (§2.6) and api_request_timestamp (§2.2); a faithful implementer rendering computed deadlines as ".000Z" (as this implementation does) fails the byte assertion while satisfying the instant rule. Per 1c split: kept the covered instant assertion, dropped the uncovered byte-format assertion.
FIX (test artifact): added `assert_timestamp_instant_equal` to test_helpers/assertions.py (parses both sides, compares instants); exported via test_helpers/__init__.py; updated 3 sites in test_04_concurrent_reviews.py and 7 sites in test_05_peer_to_peer.py.

**Cluster B — review_status MONITORING asserted without ADMISSION_REVIEWED precondition (2 tests: test_03 test_pend_resubmit_cycle_ends_in_approval_axes, test_immediate_consistency_on_approve).**
STEP 1a: PRD §3.3 verbatim: "advances `review_status` from `ADMISSION_REVIEWED` to `MONITORING` when applicable". STEP 1b: the tests' fixtures (setup_submitted_auth) never submit an admission review, so the case is INTAKE at approval — the cited sentence does not determine MONITORING from INTAKE; a faithful implementer gating on ADMISSION_REVIEWED (as this implementation does) fails. TEST IS WRONG (setup missing PRD precondition).
FIX (test_suite/test_03): both tests now submit a CRITERIA_MET admission review (attestation=True, benchmark MET) before approval, establishing ADMISSION_REVIEWED so the asserted transition is PRD-determined. Assertion itself unchanged.

**Cluster C — overturn frontier start 0 vs 1 (2 tests: test_05 test_p2p_complete_overturn_restores_auth, test_08 test_appeal_overturn_restores_auth_and_case).**
PRD §3.5/§3.8: interval "appended at the case frontier — starting at the highest existing certified end"; §2.9: "half-open intervals on a 1-based hospital-day index". With no existing intervals, frontier must be day 1 (a [0,n) interval would certify "day 0", outside the 1-based index). TEST IS FAITHFUL → implementation bug.
FIX (implementation/services/case_service.py): `case_frontier_end` returns 1 (was 0) when the case has no certified intervals.

**Cluster D — CC44 "latest review" tie under the logical clock (1 test: test_06 test_cc44_allowed_after_latest_review_not_met).**
PRD §3.6: "the case's latest submitted-or-advisor-reviewed admission review must carry a determination of CRITERIA_NOT_MET". Reviews list "in created_at ascending order" (§3.2); with the logical clock unstaggered both reviews share a created_at, and `max(key=created_at)` returns the first maximal (oldest) review → wrongly read CRITERIA_MET. "Latest" of the created_at-ascending list is its last row (stable sort, insertion order breaks ties). TEST IS FAITHFUL → implementation bug.
FIX (implementation/routes/cc44.py): latest = sorted(reviews, key=created_at)[-1].

**Cluster E — appeal filing past deadline surfaced ERR_DENIAL_NOT_FINAL instead of ERR_APPEAL_DEADLINE_PASSED (1 test: test_08 test_appeal_after_deadline_passed).**
PRD §3.8 scopes lazy CLOSED_NO_APPEAL materialization to "list and single-resource reads"; appeal filing is a write and must evaluate "logical now at or before appeal_deadline_at (ERR_APPEAL_DEADLINE_PASSED, equality allowed)" against the live OPEN denial. The implementation called maybe_close_denial() at the top of file_appeal, flipping the denial to CLOSED_NO_APPEAL and tripping the not-OPEN gate first. TEST IS FAITHFUL → implementation bug.
FIX (implementation/routes/appeals.py): removed maybe_close_denial from the filing path (with an explanatory comment); the deadline gate now reports ERR_APPEAL_DEADLINE_PASSED.

No tests deleted; no assertions weakened to status-only; no skips/xfail added.

### Iteration 2 sweep (after the 5-cluster fix batch): 94/94 passed in every one of the 8 parallel rounds (756/756 test executions). No flakiness surfaced; the failure set from iteration 1 was deterministic and is fully resolved. Task complete — no tests deleted, no assertions downgraded to status-only, no skip/xfail markers, no implementation behavior added beyond PRD-verbatim rules, no seeded data (in-memory dicts only, wiped per per-test-server restart).

## Step 8: Finalize PRD — 2026-08-14T13:20:00.000Z

Done. PRD_FINALIZED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1720_utilization_review_medical_necessity/workspace/PRD_FINALIZED.md` with 5 inline edits, each traced to a step_7_diff cluster.

## Line counts / delta

- PRD.md: 326 lines, 56,836 bytes
- PRD_FINALIZED.md: 326 lines, 57,975 bytes
- Delta: 0 lines (0.0%); +1,139 bytes (~2.0%). All edits are in-place sentence revisions/insertions on 5 existing lines; no sections added or removed.

## Changes (one bullet per edit)

- §2.11 — insert — appended a sentence pinning computed deadline/window timestamps (`review_due_at`, `window_deadline_at`, `appeal_deadline_at`) to the same three-fractional-digit ISO 8601 UTC rendering as `created_at`/`updated_at`, with a `.000Z` whole-second example — `implementation/routes/concurrent_reviews.py:30-31,79,193`, `implementation/routes/p2p.py:35-36,118`, `implementation/routes/authorization_requests.py:211` (Cluster A).
- §3.3 — revise — extended the approval sentence with "approval while the case is still in `INTAKE` (no admission review submitted) leaves the review axis untouched" — `implementation/routes/authorization_requests.py:187-188` (Cluster B; step 7's diagnosis explicitly noted the PRD did not determine the INTAKE-approval case).
- §3.5 — revise — added parenthetical to the frontier definition: "day 1 when the case has no certified intervals yet, since certified days live on a 1-based index per §2.9" — `implementation/services/case_service.py:72-79` (Cluster C).
- §3.6 — revise — defined "latest submitted-or-advisor-reviewed admission review" as "the last row of that set in `created_at` ascending order, with `created_at` ties … resolving in favor of the most recently created review" — `implementation/routes/cc44.py:94-97` (Cluster D).
- §3.8 — revise — replaced "on first touch" with "on the first such read" and added that lazy `CLOSED_NO_APPEAL` materialization is confined to reads; the appeal-filing write path evaluates preconditions against the still-`OPEN` denial, so a late filing surfaces `ERR_APPEAL_DEADLINE_PASSED` — `implementation/routes/appeals.py:77-81,102-116`, `implementation/routes/denials.py:30,38` (Cluster E).

## Per-edit pre-edit search log

**Edit 1 (§2.11, Cluster A).** (a) Subject: string rendering of server-computed deadline/window timestamps. (b) Enumerated impl paths: every `timedelta`-derived timestamp — `authorization_requests.py:202,211` (INITIAL_AUTH `appeal_deadline_at`), `concurrent_reviews.py:67,79` (`review_due_at`) and `:185,193` (CONCURRENT `appeal_deadline_at`), `p2p.py:97,118` (`window_deadline_at`); all use the millisecond format `strftime("%Y-%m-%dT%H:%M:%S.") + f"{microsecond//1000:03d}Z"`, identical to `now_iso()` in `db.py:10-14` used for all state-transition stamps and `created_at`/`updated_at`. Also checked `routes/clock.py:12-23` (clock echo, same format — not named in the edit, no conflict). Client-supplied `scheduled_start_at`/`scheduled_end_at` are echoed verbatim (`p2p.py:116-117`), so they were excluded from the claim. (c) Scoped the sentence to the three named computed fields only, matching the Cluster A boundary exactly.

**Edit 2 (§3.3, Cluster B).** (a) Subject: `review_status` transition on authorization approval. (b) Enumerated every `review_status` writer: `cases.py:60` (INTAKE at open), `admission_reviews.py:128-129` (INTAKE→ADMISSION_REVIEWED only, matching §3.2's already-pinned no-op-from-MONITORING), `authorization_requests.py:187-188` (MONITORING gated on `== ADMISSION_REVIEWED`), discharge (→CLOSED). Approval from INTAKE therefore leaves the axis at INTAKE; approval from MONITORING (second auth) stays MONITORING and is not claimed by the edit. (c) Used a conditional em-dash clause rather than a universal rule, leaving "when applicable" intact for the MONITORING-already case.

**Edit 3 (§3.5, Cluster C).** (a) Subject: case frontier start for restoration intervals. (b) Enumerated impl paths: sole definition `case_service.py:72-79` (returns 1 when empty, else max certified end); both consumers — `p2p.py:232-239` (P2P overturn) and `appeals.py:48-51` (appeal overturn/partial) — go through it. PRD references to "case frontier" exist at §3.5 and twice at §3.8; §3.8 does not redefine it. Initial/concurrent approvals take client-supplied starts, never the frontier. (c) Defined the empty-case value once at §3.5 so the §3.8 references inherit it; no §3.8 edit needed.

**Edit 4 (§3.6, Cluster D).** (a) Subject: "latest" admission review for the CC44 clinical-basis gate. (b) Enumerated impl paths: the only consumer is `cc44.py:86-100` — filters to `SUBMITTED`/`ADVISOR_REVIEWED`, then `sorted(..., key=created_at)[-1]`; Python's stable sort over dict-insertion order resolves ties to the most recently created. Cross-checked the admission-review listing endpoint (`admission_reviews.py:82-84`, `created_at` ascending per §3.2) — "last row of that set in created_at ascending order" denotes the same element. No other "latest" usage exists in PRD or impl (grep-verified). (c) Tied the definition to the listing order the PRD already pins, and noted ties arise under the logical clock.

**Edit 5 (§3.8, Cluster E).** (a) Subject: scope of lazy `CLOSED_NO_APPEAL` materialization. (b) Enumerated every `maybe_close_denial` callsite: `denials.py:30` (list), `denials.py:38` (get), `authorization_requests.py:280-282` (the authorization's denial-cases list — also a read). Write paths never call it: `appeals.py:68-116` (`file_appeal`, with the step-7 comment at :77-81 and deadline gate at :114-116), `appeals.py:148+` (`decide_appeal`), `p2p.py` complete/cancel (mutate denial status without materializing). (c) Two wording adjustments: (i) "on first touch" → "on the first such read" (the old phrase was the mismatch seed that licensed the impl bug); (ii) the added claim was scoped to still-`OPEN` denials ("a filing attempted against a still-`OPEN` denial after `appeal_deadline_at`") to avoid overclaiming gate ordering — in impl, the finality checks (`appeals.py:99-108`) run before the deadline gate, so a late filing with a conference still scheduled still surfaces `ERR_DENIAL_NOT_FINAL`. No claim was made about conference `EXPIRED` materialization, which legitimately does occur on mutation paths (`p2p.py:164,209,265`) per §3.5.

No edit was made for the step_7 test-artifact-only changes beyond Cluster A's rendering pin, and Cluster B/C/D/E implementation fixes were verified as the alignment target before wording each clause.

## Step 9: Complete PRD — 2026-08-14T13:35:00.000Z

Done. `PRD_COMPLETED.md` is produced as a minimal patch over `PRD_FINALIZED.md` — 24 in-paragraph edits, no new sections, no reformatting.

**File stats**
- Source: `workspace/PRD_FINALIZED.md` — 326 lines, 57,975 chars
- Output: `workspace/PRD_COMPLETED.md` — 328 lines, 63,786 chars
- Delta: +2 lines, +5,811 chars (26 diff hunks, all inline insertions/revisions)

**Counts: 20 ambiguity-pins, 7 mismatch-revisions**

Mismatch revisions (PRD described behavior impl does not exhibit):
- §2.4 — revise — mismatch — blanket `ERR_CASE_CLOSED` closure rule qualified: CC44 concurrence and committee-review are not closure-gated and survive discharge; only CC44 initiation (`ERR_CC44_POST_DISCHARGE`) and rescission are blocked — impl `routes/cc44.py:131-181` (no closed check) vs `cc44.py:235-236` (rescind gated)
- §2.5 steps 9/10 — revise — mismatch — reschedule cap moved from business constraints (step 10) into domain gates (step 9), evaluated before the re-applied window/calendar checks — impl `routes/p2p.py:177-185` checks cap first
- §2.9 — revise — mismatch — bed-day budget enumeration extended to overturn restorations (P2P completion, appeal OVERTURNED/PARTIAL), equality-to-budget allowed — impl `routes/p2p.py:234-236`, `routes/appeals.py:43-45`
- §3.3 — revise — mismatch — pend now pinned to increment the case `version` like the other decisions — impl `routes/authorization_requests.py:163` (`touch(case)`)
- §3.4 — revise — mismatch — concurrent-review intervals tagged with the parent authorization's *current* interval level tag (re-taggable by CC44), not the immutable `level_of_care` — impl `services/case_service.py:38` (`auth["_interval_level"]`)
- §3.5 — revise — mismatch — nonexistent `advisor_physician_id` yields `ERR_NOT_FOUND`; `ERR_NOT_PHYSICIAN_ADVISOR` only for an existing non-advisor — impl `routes/p2p.py:106-109`
- §3.7 — revise — mismatch — escalation auto-creation fires on any open-day-count recomputation (create, mitigate, appeal-overturn) leaving raw tier ≥1 with no active escalation, not only on a 0→≥1 create — impl `services/case_service.py:117-134`, called from `routes/avoidable_days.py:106` and `routes/appeals.py:214`

Ambiguity pins (PRD silent; pinned to impl):
- §2.3 — insert — pagination param validation (`ERR_VALIDATION_FAILED`), enumerated filter validation (`plan_class`/`review_status`/`auth_status`/`status`/`is_advisor`), conjunctive filters, `total_count` = filtered count, `has_more` = `offset+limit < total_count` — `routes/helpers.py:12-23`, `routes/payers.py:62-67`, `routes/cases.py:82-92`
- §2.5 step 3 — insert — bodyless action endpoints (submit/withdraw/cancel/acknowledge) accept and ignore any body — `routes/admission_reviews.py:98`, `routes/authorization_requests.py:253`, `routes/p2p.py:262`, `routes/escalations.py:33`
- §2.5 trailing — insert — unknown paths and unsupported methods → `ERR_NOT_FOUND` 404; malformed/non-object JSON → `ERR_VALIDATION_FAILED` 400 — `app.py:39-51`, `services/validation.py:9-16`
- §2.6 — insert — `version` starts at 1 on creation — `services/common.py:8`
- §2.6 — insert — advisory fields `pend_reason`, `advisor_note`, `concurrence_note`, `committee_note`, `rescind_reason` are validated but never persisted — `routes/authorization_requests.py:146`, `routes/admission_reviews.py:142`, `routes/cc44.py:137,170,229`
- §2.6 — insert — lazily materialized events (`P2P_EXPIRED`, `DENIAL_CLOSED_NO_APPEAL`) record actor `system`/`system` — `services/case_service.py:176-177,191`
- §2.11 — insert — every server-rendered timestamp (`created_at`, `updated_at`, `api_request_timestamp`, transition stamps) reads the logical clock; clock-set returns 200 with `data.current_utc` — `db.py:10-14`, `response.py:17`, `routes/clock.py:23`
- §3.2 — insert — case-create body references `payer_id`/`attending_physician_id` must resolve (else `ERR_NOT_FOUND`, in that order); `patient_mrn` has no uniqueness constraint — `routes/cases.py:46-47`
- §3.3 — insert — authorization-request reads expose computed `denial_is_final` (true iff `DENIED` with no `SCHEDULED` linked conference), whose evaluation lazily expires past-deadline conferences — `routes/authorization_requests.py:38-54`
- §3.4 — insert — concurrent PARTIAL count at/above requested → `ERR_INVALID_STATE` after the `SUBMITTED` check; decision-conditional field checks run after path resolution (unresolvable id → `ERR_NOT_FOUND` first) — `routes/concurrent_reviews.py:113-128,152-157`
- §3.5 — insert — calendar clearance lazily expires past-deadline conferences and excludes the rescheduling conference itself — `routes/p2p.py:49-56,185`
- §3.5 — insert — scheduling moves the linked denial to `P2P_SCHEDULED` only when still `OPEN` — `routes/p2p.py:125-128`
- §3.5 — insert — reschedule re-checks both logical now and the new start against the deadline — `routes/p2p.py:180-183`
- §3.5 — insert — OVERTURNED restoration itself enforces the bed-day budget — `routes/p2p.py:234-236`
- §3.5 — insert — lazy EXPIRED also fires on auth/denial reads (`denial_is_final`), physician calendar listings, and other conferences' clearance scans — `services/case_service.py:204-213`, `routes/physicians.py:64-65`, `routes/p2p.py:54`
- §3.6 — insert — service-line shape: exactly `description`/`charge_cents`/`rate_milli`, unbounded integers, empty array allowed (rebill 0) — `routes/cc44.py:36-53`
- §3.6 — insert — no submitted/advisor-reviewed review at all → `ERR_CC44_CRITERIA_STILL_MET` — `routes/cc44.py:91-93`
- §3.6 — insert — CC44 approval withdraws inpatient `SUBMITTED`/`PENDED` auths each appending `AUTH_WITHDRAWN` — `routes/cc44.py:199-205`
- §3.7 — insert — `credit_days` integer ≥1 (`ERR_VALIDATION_FAILED`); credits only on `OPEN`/`ACKNOWLEDGED`, ineligibility → `ERR_INVALID_STATE`; tier upgrade leaves `trigger_open_day_count` at its original snapshot — `routes/escalations.py:75-94`, `services/case_service.py:135-137`
- §3.8 — insert — appeal-filing precondition order pinned: `P2P_SCHEDULED`/`SCHEDULED`-conference → `ERR_DENIAL_NOT_FINAL` (no lazy conference expiry on the filing path); non-`OPEN` denial → `ERR_APPEAL_ALREADY_FILED` if an appeal exists else `ERR_DENIAL_NOT_FINAL`; deadline last — `routes/appeals.py:93-116`
- §3.8 — insert — "denied window's start" = calendar date of `denied_at`; appeal PARTIAL count violations → `ERR_VALIDATION_FAILED` before closure/state gates — `routes/appeals.py:31-33,160-164`
- §3.9 — insert — discharge appends `ESCALATION_RESOLVED` per auto-resolved escalation and leaves open CC44 requests untouched — `routes/cases.py:132-139`

Not pinned (deliberately): non-transactional in-memory side effects when a mid-cascade budget check fails (e.g. `routes/p2p.py:225-236` mutates the conference before the 422) — the PRD never speaks to failure-path atomicity, and tests do not exercise it.
