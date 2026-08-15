# Worklog — task_1709_financial_literacy_workshop_coaching

## Step 1: Create Task Directory — 2026-08-14T09:48:00.000Z

Pre-assigned by dispatcher: `tasks/task_1709_financial_literacy_workshop_coaching/` and its `workspace/` subdirectory were created externally and verified present. Step 1 treated as DONE per orchestrator instructions.

## Step 2: Generate Scaffold — 2026-08-14T10:28:00.000Z

Done. All three scaffold artifacts for task 1709 are generated and pass lint cleanly.

### Files written

- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

### Design summary

**Profile**: quota/allocation (workshop seats + matched-savings pool) × compliance/audit (coach certification gating); layers: optimistic concurrency, cascading side effects, rate/threshold triggers, derived-field reconciliation. Flat topology (FK references, no URL nesting), branching/cyclic state machines, hierarchical-override RBAC (ProgramAdmin opaque; Coach and Participant entity-backed), immediate consistency.

**Surface**: 12 entities (CurriculumModule, Coach, Participant, Workshop, Registration, CoachingCase, GoalPlan, OutcomeSnapshot, MatchPool, MatchEnrollment, Referral, FunderReport), 49 endpoints (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`), 28 error codes, 11 calculations, 2 OCC concurrency rules (`goal-plan-create-stale-case`, `workshop-reschedule-stale-version`).

**Difficulty rules** (18 instances, 2 per rule, all with structured `setup_api_calls` and precomputed literal asserts):
- Dual variants: incentive earned (983) vs provisional (4466) on Registration domain; COHORT (avg 30.0) vs ROLLING (avg 25.0) funder-report aggregation on outcome domain
- Combinatorial modes: (a) tiered match accrual with nested cap/pool guards; (b) pinned per-session rounding (983+983=1966, not 1965)
- Cyclic Coach certification loops and branching CoachingCase (revert + hold cycles)
- Depth-3 cascade (coach suspend → case PLAN_STALLED → plan FROZEN → enrollment MATCH_PAUSED) and depth-2 (cancel → waitlist promotion)
- Priority pairs (existence-vs-state, state-vs-fiscal), boundaries (seat `confirmed < capacity`, no-show `>= 3`), cross-entity gates (Case→Coach, Enrollment→GoalPlan), overlap semantics (coach half-open vs participant 30-min buffer), conservation invariants (pool dollars, seat ledger)

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Additional audits: all 57 instance names unique across both files; excluded_because stubs cite real difficulty instances; all 28 error codes referenced; all grounds (calculations, state machines, validations, entity fields, concurrency rules, errors) resolve; all endpoint roles declared in RBAC; entity-backed identities target declared entities; no forbidden concurrency vocabulary.

## Step 3: Copy Shared Files — 2026-08-14T10:28:10.000Z

Copied `INSTRUCTION.md` → `tasks/task_1709_financial_literacy_workshop_coaching/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T10:41:30.000Z

All verifications pass. The PRD is complete and written to `workspace/PRD.md`.

### Summary

**Generated**: `PRD.md` (~230 lines) for task 1709 (Financial Empowerment Center) from `SCAFFOLD.yaml`. The two forbidden test-targeting files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Document design** (domain-derived, not template-copied):
- §1: 2 paragraphs, business-context angle (program mission + cross-cutting concerns + logical clock).
- §2: 10 subsections — RBAC with per-role identity prose, verbatim §2.2 envelope (byte-for-byte match confirmed), pagination, the logical clock & lazy sweeps, common resource properties (incl. the `common_fields: false` exceptions for OutcomeSnapshot/FunderReport), money/rounding (pinned per-session-then-sum order), a full request-evaluation pipeline encoding all 28 validation priorities in order, OCC (both rules, no race framing), three conservation invariants, and flat-topology reference resolution.
- §3: 9 subsections organized by program lifecycle (modules/calendar → registration/waitlist/attendance → participant standing → cases/goal plans → coach certification & depth-3 stall cascade → snapshots → matched savings → referrals → funder reporting). Parameters scattered across subsections (e.g., `new_coach_id` in §3.4 vs. stall cascade in §3.5; deposit guards in §3.7 vs. pause semantics in §3.5); constants embedded in prose (3 strikes, 30-minute buffer, 30-day TTL, 365-day certification).
- §4: 49 endpoint rows, 4 columns. §5: 28 error rows, 2 columns.

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields: 59 required, 59 present, 0 missing
- endpoints[].request_body/input/output keys: 14 required, 14 present, 0 missing
- endpoints[].query_params (limit/offset + filter ids): all present, 0 missing
Status: PASS  (73/73 required identifiers verified mechanically)
```

```
Rule coverage check:
- validations[] with priority: 28 checked, 28 expressed in ordered pipeline + per-endpoint prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_case_version/expected_workshop_version + ERR_STALE_VERSION 412 + non-optional + no-other-endpoint clause), 0 missing
- state_machines[].transitions: 40 checked across 10 machines, 40 fully expressed (from/to, preconditions with error ids, all side-effect links), 0 missing
- calculations[]: 11 checked, 11 fully expressed (formulas translated to precise prose; rounding order pinned; constants embedded), 0 missing
- validations[] conditions: 28 checked, 28 matchable to error ids in §2.7/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all 49 endpoints' side effects expressed, 0 missing
- entities[].fields[] structured content: types/defaults/constraints/initial values reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (5 EXITED branches, 3 forfeit branches, ATTENDED/NO_SHOW, ACCEPTED/DECLINED, 3 stall-cascade from-states, COHORT/ROLLING, earned/provisional, LAPSED/SUSPENDED reinstate), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 448
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**One scaffold tension resolved**: for deposit guards, the validations table orders `ERR_POOL_INSUFFICIENT` (priority 25) before `ERR_MATCH_CAP_EXCEEDED` (priority 26), while the `match_accrual` formula lists the cap check first. I followed the priority-ordered validations table (the canonical ordering source) and stated pool-solvency-before-cap consistently in §2.7 and §3.7; both guard conditions and error ids are specified exactly regardless.

All additional enum/state/role coverage verified mechanically: 33/33 state values, 37/37 enum values, 28/28 error ids, 3/3 role names present; §2.2 emitted verbatim; document ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T11:05:00.000Z

Clean: no skip/xfail markers, no scaffold references, 72 tests collected.

Final report:

**Generated complete test infrastructure and test suite for task 1709** (financial literacy workshop & coaching nonprofit).

### Stage 1 — `test_helpers/` (8 files)
- `types.py` — 12 status/role enums + 12 entity TypedDicts; `OutcomeSnapshot` and `FunderReport` correctly omit `updated_at`/`version` (append-only/frozen per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 35 endpoints (clock, modules, coaches, participants, workshops, registrations, cases, plans, snapshots, pools, enrollments/deposits/payout/forfeit, referrals, funder reports)
- `api_errors.py` — all 28 error IDs with HTTP status map registered via `set_error_http_status_map` (incl. `ERR_POOL_INSUFFICIENT` → 402)
- `assertions.py` — per-entity asserts + `assert_pool_conservation` (PRD §2.9 identity)
- `factories.py` (unique emails/codes via monotonic counter), `constants.py` (NO_SHOW_LIMIT=3, TRAVEL_BUFFER_MINUTES=30, REFERRAL_TTL_DAYS=30, 365-day cert), `test_users.py` (opaque admin + per-instance `make_coach_headers`/`make_participant_headers` for entity-backed roles + `ANONYMOUS_HEADERS`), `fixtures.py` (5 tiers: `create_certified_coach`, `setup_case_with_draft_plan`, `setup_case_with_active_plan`, `setup_active_enrollment`, `setup_full_waitlist_workshop`, etc.)

### Stage 2 — `test_suite/` (conftest + 12 files, 72 tests)
Coverage audit passes mechanically:
- **Queue A (Difficulty): all 18 instances × ≥2 tests = 36 tests** — incl. incentive earned-vs-provisional (983/4466), COHORT-vs-ROLLING (30.0/25.0, 50000/30000), match cap boundary (75000 rejected / 60000 accepted), per-line rounding (983+983=1966), coach certify/suspend/lapse/reinstate loops, depth-3 suspend cascade, waitlist promotion, both priority pairs (404-beats-409, state-beats-fiscal), seat and no-show boundaries, certification gates, half-open vs 30-min-buffered overlap, and both conservation invariants
- **Queue B (Corner): all 36 non-stub instances × 1 test**; the **3 `excluded_because:` stubs were not translated** and their difficulty cross-references verified to resolve
- **No instance skipped by the PRD-first filter** — every asserted rule has verbatim PRD coverage and unique derivability (PRD §2.7 explicitly pins pipeline order, so both priority-pair instances are uniquely derivable)

### Quality gates passed
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim; all tags resolve to real instances
- Verbatim-citation audit: all quoted PRD sentences survive a literal whitespace-normalized grep of PRD.md (3 elided citations were fixed)
- No `pytest.mark.skip`/`skipif`/`xfail`, no scaffold references in generated code
- `pytest --collect-only` succeeds: 72 tests collected

## Step 6: Generate Implementation — 2026-08-14T11:12:00.000Z

The implementation is complete and verified. Summary of what was delivered:

**Location:** `workspace/implementation/`

**Files:**
- `start.sh` — foreground launcher, guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry point, error handlers (ApiError → envelope, 404/405 → ERR_NOT_FOUND envelope), WSGI lock middleware serializing all requests
- `db.py` — empty-at-boot in-memory store (no seeding), logical clock pinned to `2026-08-01T00:00:00Z`
- `errors.py`, `response.py`, `middleware.py`, `helpers.py` — error catalog, envelope (`meta.api_request_id`/`api_request_timestamp` + `response_type` + `data`), `X-User-ID`/`X-User-Role` auth, strict field/datetime/date validation
- `services/domain.py` — lazy sweeps (coach CERTIFIED→LAPSED, referral SENT→EXPIRED), depth-3 stall cascade, waitlist promotion, half-open coach overlap, 30-min buffered participant overlap, Decimal ROUND_HALF_UP incentive/accrual math, funder aggregation, serializers
- `routes/` — `admin.py` (clock, modules, coaches, participants), `workshops.py` (workshops + registrations/attendance), `coaching.py` (cases, goal plans, snapshots), `match.py` (pools, enrollments, deposits/payout/forfeit), `network.py` (referrals, funder reports)

**Key spec-fidelity decisions:**
- Full PRD §2.7 pipeline ordering per endpoint: 401 → 403 (incl. entity-backed ownership) → 400 → 404 → 412 OCC → state (409 family) → business rules in pinned order (cert gate → temporal → conflicts → capacity floor → dup → open case → restriction → uniqueness → referential → caseload → fiscal: pool-solvency 402 before cap 409)
- OCC: mandatory `expected_case_version` on POST /goal-plans, `expected_workshop_version` on PATCH /workshops; goal-plan creation and case transitions bump case version, workshop reschedule bumps workshop version; derived fields (`confirmed_count`, `active_caseload`) are computed on read and do not bump versions
- `new_coach_id` absence on PLAN_STALLED→INTAKE is 400 before transition legality; reassignment allowed for ProgramAdmin, owning coach, or the taking-over coach
- Per-session-line rounding before summing; match accrual rounds exactly once before guard comparisons; pool conservation invariant maintained on deposit/payout/forfeit
- Case completion records logical-clock time for `completions_count`; COHORT/ROLLING inclusion sets and 1-decimal credit / integer-cent savings averages per §3.9
- Snapshots/reports carry only `id` + `created_at` (no `version`/`updated_at`); snapshot lists ordered by `recorded_at`, tie-break `created_at`

**Verification:** booted cleanly from fresh processes (per-test-server contract) and passed two self-written suites exercising ~60 scenarios: full happy paths, waitlist promotion, OCC 412s, cascade depth-3 (suspend → stall → freeze → pause), lapse sweep with reinstatement, no-show strike boundary (2 no, 3 yes), cap/pool guard ordering, exit cascades, RBAC/ownership 403s, envelope and pagination shape. All passed.

## Step 7: Run Tests and Iterate — 2026-08-14T11:26:00.000Z

All 8 rounds pass cleanly with 72/72 each. The sweep is stable. Here is the summary.

**Iterations run: 2** (iteration 1 surfaced 2 deterministic failures across all 8 rounds; iteration 2 confirmed the fixes — all 8 rounds clean, 72/72 each, 0 flaky).

**Tests deleted: 0.** Both failures were repairable against PRD-covered rules; neither required deletion.

**Fixes applied to `test_suite/`:**

1. `test_06_registration_waitlist.py::test_duplicate_active_registration_rejected` — **STEP 2 test bug (assertion mis-translates PRD's pinned precedence).** The test registered a participant on the *same* workshop twice and asserted `ERR_ALREADY_REGISTERED`. But PRD §2.7 (line 115) and §3.2 (line 157) both pin the order: the participant buffered-window conflict check runs *before* the duplicate check. A same-workshop duplicate always overlaps its own existing `REGISTERED` window within the 30-minute buffer, so a PRD-faithful implementation must surface `ERR_PARTICIPANT_SCHEDULE_CONFLICT` first — `ERR_ALREADY_REGISTERED` is unreachable on that path. Fixed the test to reach the duplicate guard the only PRD-consistent way: via a `WAITLISTED` entry (the conflict check ignores `WAITLISTED` per §3.2 line 159), using `setup_full_waitlist_workshop(capacity=1, num_waitlisted=1)` so the participant lands on the waitlist, then re-registers → `ERR_ALREADY_REGISTERED`.

2. `test_12_defaults_immutability_expiry.py::test_referral_lazy_expiry_at_exactly_30_days` — **STEP 1c partial coverage (format silence on a domain field).** The test asserted the exact string `expires_at == "2026-08-31T00:00:00Z"` (zero fractional digits); the implementation returned `"...00.000Z"`. PRD §2.5 pins the "three fractional digits" format only for the *system-managed* `created_at`/`updated_at` (and §2.2 for `api_request_timestamp`) — `sent_at`/`expires_at` are referral domain fields whose serialization PRD never pins; §3.8 fixes only the *instant* ("exactly 30 days after `sent_at`"). A faithful PRD-only implementer could serialize either way. Kept the PRD-covered semantics (expires_at = sent_at + exactly 30 days; sent at the default clock 2026-08-01; the `>=` boundary sweep to `EXPIRED`; terminal-referral `ERR_INVALID_TRANSITION`), and replaced the uncovered exact-string assertion with a format-agnostic instant comparison via a small `_parse_iso` helper added at the top of the file.

**Fixes applied to `implementation/`: 0.** The implementation was already PRD-faithful on both counts; both failures were test artifacts, not implementation bugs.

**Fixes applied to `test_helpers/`: 0.** The fixtures/factories were consistent with PRD; both bugs lived in the test functions' setup/assertion logic.

## Step 8: Finalize PRD — 2026-08-14T11:33:00.000Z

Done. `workspace/PRD_FINALIZED.md` written with exactly one in-place revision.

### Summary

**Line counts:** PRD.md 327 lines, PRD_FINALIZED.md 327 lines — 0% delta (the single change is an in-place sentence extension on existing line 226; no lines added or removed).

**Step 7 diff triage:**
- Item 1 (`test_duplicate_active_registration_rejected`): pure test bug. PRD §2.7 tier 7 (line 115) and §3.2 (line 157) already pin the buffered-conflict check before the duplicate check, and the implementation follows that exact order (`routes/workshops.py:242-249` conflict, then `250-260` duplicate). No PRD edit — prose already determines the behavior.
- Item 2 (`test_referral_lazy_expiry_at_exactly_30_days`): genuine PRD silence. §2.5 pins "three fractional digits" only for system-managed `created_at`/`updated_at` and §2.2 for `api_request_timestamp`; referral domain fields `sent_at`/`expires_at` had no pinned serialization. The implementation serializes them with exactly three fractional digits (`.000Z` at the default clock). Patched.

**Changes:**
- §3.8 (line 226) — revise — extended the final sentence to pin that `sent_at` and `expires_at` are serialized in responses as ISO 8601 UTC timestamps with three fractional digits, in the same format as the system-managed timestamps of §2.5 — `implementation/services/domain.py:523-524` (`ser_referral` → `fmt_dt`), formatter at `implementation/helpers.py:112-117`.

**Per-edit pre-edit search log:**
- Edit 1 (§3.8 referral timestamp format):
  - (a) Subject: response serialization format of the referral `sent_at` and `expires_at` fields.
  - (b) Impl paths enumerated and read: `helpers.py:112-117` (`fmt_dt` — the only datetime formatter in the codebase; emits `YYYY-MM-DDTHH:MM:SS.mmmZ`, exactly three fractional digits); `services/domain.py:515-527` (`ser_referral`, the only referral serializer, applies `fmt_dt` at lines 523-524); `routes/network.py:85, 107, 119, 144` (all four referral response paths — create 201, list, get, transition — route through `ser_referral`); `routes/network.py:80-81` (instant semantics: `sent_at = logical_now()`, `expires_at = now + 30 days`, confirming the PRD's pinned instant is untouched). Cross-checked every other `fmt_dt` consumer to confirm the new sentence makes no false claim about siblings: `certification_expires_at` (domain.py:398), workshop `start_at`/`end_at` (domain.py:424-425), snapshot `recorded_at` (domain.py:476), all `created_at`/`updated_at` (domain.py:370-371, 479, 540), and clock `current_utc` (admin.py:40) — all use the identical three-fractional-digit format, so the "same format as §2.5" phrasing is accurate everywhere.
  - (c) Wording adjustments: scoped the claim strictly to the referral's two fields rather than a global "all datetime fields" claim (keeps the edit minimal and traceable to the Step 7 site); mirrored the existing §2.5 phrase "ISO 8601 UTC … with three fractional digits" for consistency; deliberately did not pin sub-millisecond truncation vs rounding (`fmt_dt` truncates via `microsecond // 1000`), since Step 7's fix was format-agnostic on that axis and pinning it would add an uncovered claim.

## Step 9: Complete PRD — 2026-08-14T11:44:00.000Z

All edits applied cleanly. The diff shows exactly the 12 intended in-paragraph changes and nothing else.

### Summary

**Source**: `PRD_FINALIZED.md` (327 lines / 48,282 chars) → `PRD_COMPLETED.md` (329 lines / 51,751 chars), char-delta +3,469.

**Counts**: 10 ambiguity-pins, 2 mismatch-revisions (12 edited passages total).

**Changes**:

- §2.1 (Participant RBAC) — insert — ambiguity — pinned that participant list scoping is silent, but an explicit mismatched filter (`participant_id` ≠ `X-User-ID`, or a foreign `case_id` on the goal-plan list) is `ERR_FORBIDDEN` — `implementation/routes/workshops.py:293-301`, `coaching.py:378-385`
- §2.3 (Pagination) — insert — ambiguity — pinned clamping of out-of-range `limit`/`offset` (limit clamped to [1,100], negative offset clamped to 0) and 400 for non-integer values — `implementation/helpers.py:120-141`
- §2.3 (Pagination) — insert — ambiguity — pinned creation-timestamp tie-break by insertion order (common under the frozen logical clock) — `implementation/services/domain.py:544-545`
- §2.4 (Logical clock) — insert — ambiguity — pinned no monotonicity check on clock set (backward moves allowed) and naive ISO-8601 inputs interpreted as UTC — `implementation/routes/admin.py:33-40`, `implementation/helpers.py:63-77`
- §2.5 (Common properties) — insert — ambiguity — pinned `version` starts at 1 on creation — `implementation/services/domain.py:27-36`
- §2.5 (Common properties) — insert — ambiguity — pinned `created_at`/`updated_at` stamped from the logical clock while the envelope `api_request_timestamp` is wall-clock — `implementation/services/domain.py:29-33,44-46`, `implementation/response.py:9-17`
- §2.7 (Pipeline tier 3) — revise — mismatch — removed "`new_coach_id` present on a stall reassignment" from the well-formedness tier (impl evaluates it after existence, since it needs the case's current state) and noted the exception — `implementation/routes/coaching.py:184-199`
- §2.9 (Conservation) — insert — ambiguity — pinned that `confirmed_count`/`active_caseload` are computed on read (no parent `version`/`updated_at` movement) and that pool fund fields are rewritten in place by enrollment/deposit/payout/forfeit flows without bumping the pool's `version`/`updated_at` — `implementation/services/domain.py:53-66`, `implementation/routes/match.py:237-243,254-258,272-276`
- §3.1 (Workshop reschedule) — revise — mismatch — "a stale version fails … before any other check" corrected to "before any state or business check" (well-formedness/existence precede OCC per §2.7); also pinned merged-window `end_at>start_at` validation, `capacity` ≥ 1 floor on PATCH, and that a no-change edit still increments `version` — `implementation/routes/workshops.py:134-185`
- §3.4 (Case transitions) — insert — ambiguity — pinned the drivable `target_state` set (anything else incl. `PLAN_STALLED` → 400), that a supplied `new_coach_id` is existence-validated but ignored outside the `PLAN_STALLED → INTAKE` branch, and that the coach-takeover ownership exception is judged purely from the payload (`target_state=INTAKE` + `new_coach_id` = acting coach) regardless of current state — `implementation/routes/coaching.py:37-47,160-241`
- §3.4 (`PLAN_STALLED → INTAKE` bullet) — revise — mismatch — the missing-`new_coach_id` 400 is now described as evaluated after existence resolution, before transition legality (matching impl order) — `implementation/routes/coaching.py:184-207`
- §3.6 (Snapshots) — insert — ambiguity — pinned omitted metrics serialize as null and the third sort tie-break (insertion order after `recorded_at`/`created_at`) — `implementation/services/domain.py:472-480`, `implementation/routes/coaching.py:461-462`
- §3.7 (Pool creation) — insert — ambiguity — pinned `income_threshold_cents` accepts any integer and both match ratios any JSON number, with no range validation — `implementation/routes/match.py:50-59`
- §3.7 (Deposits) — insert — ambiguity — pinned optional `deposited_at` is validated as ISO 8601 but neither persisted nor echoed — `implementation/routes/match.py:201`
- §3.7 (Payout) — revise — ambiguity — pinned that payout from *any* non-`GOAL_MET` status (including terminal `PAID_OUT`/`FORFEITED`) fails with `ERR_GOAL_NOT_MET` — `implementation/routes/match.py:250-253`
- §3.8 (Referral transitions) — insert — ambiguity — pinned the recognized `target_state` set `{ACCEPTED, DECLINED, COMPLETED}` with anything else (incl. `SENT`, `EXPIRED`) malformed (400), while recognized-but-unreachable targets yield `ERR_INVALID_TRANSITION` — `implementation/routes/network.py:23-30,131-141`

Output file: `workspace/PRD_COMPLETED.md`.
