# Worklog — task_0596_identity_protection

## Step 1: Create Task Directory — 2026-07-12T00:00:00.000Z

Created `tasks/task_0596_identity_protection/` and `tasks/task_0596_identity_protection/workspace/` (directory ID pre-allocated by the caller; no scan of `tasks/` performed).

## Step 2: Generate Scaffold (Expert) — 2026-07-12T00:45:00.000Z

All three artifacts are written and `scaffold_lint.py` reports **`VERDICT: clean lint`** (610 calls scanned, 0 violations).

## Files
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

## Complexity profile (Expert)
`workflow_orchestration` + `compliance_audit`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; topology `graph`; shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`. `api_prefix: /idp`.

## Surface
- **11 entities**: Plan, Subscriber, FamilyMember, BureauProfile, ThawWindow, Alert, Specialist, SpecialistEngagement, RestorationCase, InsuranceClaim, WalletItem.
- **8 state machines**: Subscriber×2 (parallel dims `enrollment_status` × `monitoring_status`), BureauProfile (true cycle UNFROZEN→FREEZE_PENDING→FROZEN→THAW_PENDING→UNFROZEN), Alert (branching CONFIRM_FRAUD vs DISMISS with disjoint side effects), RestorationCase (cycle IN_PROGRESS↔PENDING_SUBSCRIBER), InsuranceClaim (branch + SUPERSEDED), WalletItem, Specialist (compound/derived).
- **8 calculations**: `composite_credit_score` (weighted, renormalised, empty-set→null), `identity_risk_score` (**dual-variant** LIVE vs UNDERWRITING), `claim_reimbursement` (**dual-variant** PROVISIONAL vs FINAL; rounding order pinned per-line-item), `alert_escalation_tier` (circular dependency, pre-transition snapshot pinned), `required_specialist_tier`, `specialist_selection` (full eligibility/rank/tie-break/empty-pool), `specialist_active_case_count`, `insurance_remaining`.
- **22 validations** (ordered), **48 endpoints** (incl. `POST /idp/_clock/set_current_utc`, default `2026-05-01T00:00:00Z`), **32 error codes**, **5 roles** (Anonymous, Subscriber `entity_backed:Subscriber`, RestorationSpecialist `entity_backed:Specialist`, ClaimsAdjuster `opaque`, PlatformAdmin `opaque`), **2 OCC concurrency rules** (`claim-create-stale-case`, `engagement-create-stale-specialist`).

## §1.8 / §1.9
- **§1.8**: 9 rule_ids × 2 = **18 instances**. All formula-derived asserts were computed in Python and pinned as literals (e.g. provisional 382003 vs final 374503; wrong sum-then-round answer 374502 explicitly excluded; escalation TIER2 from r0=63 vs the naive TIER3 from post-transition 73; composite 695/682; risk 58 vs 35).
- **§1.9**: 9 sections, **57 instances** (50 with full recipes + 7 `excluded_because` stubs pointing at §1.8 instances).

## Notable design notes
- Endpoint count (48) sits above the Expert guideline band of 20–32. Driven by the eight sub-domains in the scenario plus the mandatory FK reverse-reachability GET per FK; density was kept by making entities interact (assign→caseload→capacity→selector-exclusion; pay→remaining→exhausted→submit-blocked).
- Caught and fixed an enum-closure hole during self-review: `FamilyMember.monitoring_status = NOT_COVERED` originally had no producer (the child-monitoring rule rejected creation outright). Reworked so CHILD rows on non-child plans are created as `NOT_COVERED`, and `ERR_CHILD_MONITORING_NOT_INCLUDED` now fires when an Alert is raised against a NOT_COVERED member — both the enum value and the error are now reachable.
- Rule 8's two overlap rules use genuinely different interval arithmetic: ThawWindow = closed intervals, capacity 1, adjacency collides; SpecialistEngagement = half-open `[start,end)` + 60-min buffer + aggregate `max_concurrent_engagements`.

## Step 3: Copy Shared Files — 2026-07-12T00:46:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0596_identity_protection/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-12T00:53:00.000Z

**Output:** `workspace/PRD.md` — 351 lines.

**Sections written**
- **§1 Introduction** — 3 paragraphs (domain framing, the eight concerns, the two properties that make it hard: cascading multi-entity writes and the dual risk numbers).
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC (all 5 roles + every `identity:` translated), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties & the Logical Clock, 2.5 Validation Precedence (all 22 priorities as an ordered list with worked disambiguation), 2.6 OCC on Cases & Specialist Calendars, 2.7 Enrollment Gating, 2.8 Cascade Discipline & Derived Values (both conservation invariants), 2.9 Money/Weights/Rounding.
- **§3 Business Logic** — 7 subsections grouped by lifecycle: 3.1 Plans/Enrollment/Verification cascade + suspend-reactivate, 3.2 Family coverage, 3.3 Bureau files (score composite, freeze cycle, thaw windows), 3.4 Protected wallet & lost-item assist, 3.5 Alert triage & the two risk numbers (incl. pinned escalation order), 3.6 Restoration (specialists, selection policy, engagements, info loop, resolve), 3.7 Reimbursement (claims, adjudication, segregation of duties, budget).
- **§4** endpoint table — 48 rows. **§5** error table — 32 rows.

**Coverage audit (all PASS)**
- Field coverage: 61/61 entity fields, 45/45 request bodies, 10/10 query params, 1/1 path params, 3/3 computed-read outputs. PASS
- Rule coverage: 22/22 validations, 2/2 OCC rules, 36/36 state transitions, 8/8 calculations, 48/48 endpoint side-effect sets, 61/61 structured fields, 6/6 sibling-branch symmetry groups. PASS
- Path purity (§3 only): 521 backtick tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path. PASS

All 32 `errors[].id` values are mentioned in §2/§3 narrative before appearing in the §5 table. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-07-12T01:19:00.000Z

## Files written

**`test_helpers/`** (9 files) — `types.py` (11 entity TypedDicts + 16 enums), `api_client.py` (`ApiClient` with 47 endpoint methods over `/idp`), `api_errors.py` (32 error IDs registered with the framework's HTTP-status cross-check), `assertions.py` (11 entity assertions + `assert_instant_equals`, `assert_specialist_status_invariant`, `assert_open_caseload_conserved`, `assert_insurance_budget_conserved`), `factories.py`, `constants.py`, `test_users.py` (per-instance builders for the two `entity_backed` roles + an `X-User-ID`-less builder for `Anonymous`/401 tests), `fixtures.py` (5 tiers, incl. `setup_resolved_case` → `setup_paid_claim` chains, `setup_escalation_ready`, `setup_two_specialists_two_open_cases`), `__init__.py`.

**`test_suite/`** (10 files) — `conftest.py` + 9 domain-language test files, `test_01`…`test_09`.

## Counts

- **86 tests**, all collected cleanly by pytest (`86 tests collected`, zero import errors).
- **68 / 68 non-stub instances translated, 0 skipped.**
  - Queue A: all 18 difficulty instances (9 rules × 2), each with exactly 2 tests → 36 tests.
  - Queue B: all 50 non-stub corner instances, 1 test each → 50 tests.
  - The 7 `excluded_because:` corner stubs were **not** translated; all 7 `difficulty_instance` cross-references were verified to resolve to real names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.

## Audits run

- **Design-tag audit**: 86 tests / 86 tags / 0 dangling / 0 dual-tagged; every tag ends the docstring as its last line.
- **PRD-citation audit (C1)**: every quoted block ≥40 chars in every docstring was matched against a whitespace-normalised `PRD.md` — **all verbatim**, zero paraphrases.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no scaffold references leaked into generated code.

## Notable judgement calls

- **Timestamp assertions** (`score_pulled_at`, `reported_lost_at`, `escalation_deadline`) compare *instants* via `assert_instant_equals`, not literal strings. The PRD pins the instant (logical clock + SLA) but does not pin the serialisation of these three fields, so a literal compare would have failed the two-reader test while the instant compare preserves the full assertion.
- **`version == 1` at creation** is asserted where the design index pins it. PRD §2.4 states only "increments by exactly one on every mutation"; a 1-based counter is the sole reading consistent with every pre-computed value in both indices.
- `Corner/entities/plan_create_system_fields_input_ignored` was kept: PRD §2.5 enumerates a closed list of five body-schema breaches, and an unknown extra field is not among them, so a faithful PRD-only reader ignores rather than 400s.

## Step 6: Generate Implementation — 2026-07-12T01:19:00.000Z

## Files written (20)

`workspace/implementation/`
- `start.sh` — guarded `pip install` (only when `flask` is missing) + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (blueprint registration + error handlers)
- `db.py` — in-memory dicts, logical clock, `new_row`/`touch` for the four common fields
- `errors.py` — 32-entry error catalogue with HTTP codes
- `response.py` — `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination
- `middleware.py` — auth, RBAC, existence, ownership, body schema, enrollment gate
- `serializers.py`
- `services/calc.py`, `services/alerts.py`
- `routes/` — `plans.py`, `subscribers.py`, `bureau.py`, `wallet.py`, `alerts.py`, `cases.py`, `specialists.py`, `claims.py`, `clock.py`

## Endpoints: 48 (all of PRD §4, including `POST /idp/_clock/set_current_utc`)

## Organization
- **State**: 11 dicts on a single `Store` singleton, empty at boot — nothing seeded. A monotonic `_seq` on every row gives a deterministic insertion order used for `created_at ASC` listings and the specialist-selection tie-break. Logical clock starts at exactly `2026-05-01T00:00:00Z`; all timestamps read it, never wall-clock.
- **Calculations** (`services/calc.py`, all `Decimal` + `ROUND_HALF_UP`): composite score with weight renormalisation over scored bureaus only; the two risk variants sharing one skeleton but differing in `COUNTED_STATUSES` and the 1.20 family-child multiplier; claim reimbursement with per-line-item rounding *before* category sums, sublimits, deductible, then remaining-budget cap; escalation tier from the pre-transition `risk_score` snapshot; specialist selection; half-open engagement intervals extended by a 60-min buffer; closed-interval thaw-window overlap.
- **Derived fields are recomputed from scratch**, so both conservation properties hold.
- **Validation precedence** follows PRD §2.5 literally.

Note: Step 5 completed before Step 6 was dispatched (orchestrator sent them in sequence, not in one message). Physical isolation was replaced by an explicit hard constraint in the Step 6 prompt forbidding any read of `test_helpers/`, `test_suite/`, or either design index.
