# Worklog — task_1964_cut_sew_apparel_factory

Scenario: 1964. Cut-&-Sew Apparel Factory (domestic): tech pack & size grading, marker making & fabric utilization, bundle ticketing & piece-rate payroll, style/color/size (SKU) work-in-process, sewing line balance & operator efficiency, quality audit AQL & rework loop, trim shortage hold, made-in-USA content claim

## Step 1: Create task directory — 2026-08-15T03:21:00.000Z

Pre-existing (completed by pipeline launcher): `tasks/task_1964_cut_sew_apparel_factory/` and `tasks/task_1964_cut_sew_apparel_factory/workspace/` created. Orchestrator skips index scan per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-15T04:15:00.000Z

## Summary — task_1964_cut_sew_apparel_factory

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1964_cut_sew_apparel_factory/`):
- `SCAFFOLD.yaml` (1895 lines) — §1.0–§1.7 only; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (781 lines) — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` (1390 lines) — single `scaffold_corner_design:` key

**SCAFFOLD.yaml contents:**
- **Complexity profile**: workflow_orchestration × quota_allocation; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; flat topology; parallel state-machine shape; segregation_of_duties role model; immediate consistency.
- **15 entities**: Style, TechPack, OperationSpec, TrimItem, TrimRequirement, FabricRoll, ProductionOrder, Marker, Bundle, SewingLine, LineAssignment, Operator, PieceWorkEntry, PayrollRun, QualityAudit (self-referential `re_audit_of_audit_id` re-audit chain; TrimRequirement as TechPack×TrimItem junction).
- **9 state machines + 2 3 concurrency rules**: TechPack revision cycle + supersede; ProductionOrder with three parallel dimensions (production / trim-hold / quality rework loop); Bundle rework cycle with `pre_rework_status` restore; PayrollRun CALCULATED→OPEN recalc loop; FabricRoll RECEIVED→AVAILABLE/REJECTED/DEPLETED. OCC rules: `tech-pack-review-stale-style`, `marker-approve-stale-roll`, `payroll-calculate-stale-run` (all pass §1.2.1's serial-observability filter).
- **10 calculations** incl. dual variants in 3 domains (piece-rate straight vs guaranteed-minimum; domestic content cost-basis vs unit-basis; marker gross vs net utilization), combinatorial modes (a) AQL tiered table, (b) trim per-line-ceil-then-sum, (c) payroll pinned evaluation order; constants pinned (END_LOSS_PCT 0.02, SPLICE 0.5, guarantee 1500c/hr, bonus tiers 90/100, changeover buffer 15 min, cost threshold 0.70, full AQL letter/sample/Ac-Re table).
- **41 validations** in strict priority bands (auth → existence → schema → OCC → state → safety/SoD → referential → constraint → temporal → fiscal); 3 segregation-of-duties rules (self-review, self-approve, re-audit self-recheck).
- **61 endpoints, 41 errors, 10 roles** (9 functional + Any pseudo-role; SewingOperator is `entity_backed:Operator`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 20 instances across all 9 rules (dual_variant 3, combinatorial 3 covering modes a/b/c, all others 2) — cascades of depth 4 (audit-fail → order → bundles → auto-reject LOGGED entries) and depth 3 (pay → entries → operator metrics); every numeric assert pre-computed to literals (e.g., payable 2560 = 1200 piece + 1300 topup + 60 bonus; reserved 9+5=14 vs naive 13; gross 96.9/net 98.0; grading XL 20.75/XS 19.25).

**SCAFFOLD_CORNER_DESIGN.yaml**: 71 instances (56 active with full structured `setup_api_calls`, 15 `excluded_because:` stubs citing §1.8 instances) across all 9 guide sections — includes envelope shape, pagination, filtered lists, all RBAC denials, every error code's trigger, and both interval-overlap semantics (line aggregate capacity vs operator buffered exclusion).

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint` (1002 calls scanned; one FK_REVERSE_UNREACHABLE found and fixed by adding `GET /styles`). Additionally machine-checked: union name uniqueness (91), stub citations resolve, all grounds resolve, validation priorities unique (fixed a YAML float collision 4.10→4.12/4.13), no forbidden concurrency vocabulary, every error referenced.

**Honest caveat**: endpoint count (61) exceeds the Expert guideline band (20–32). §0.4 explicitly marks the bands as guidelines ("not hard rules"); the surface is driven by the scenario's 8 feature areas plus the lint-enforced reverse-reachability GETs for 10 FK relations. All hard constraints (envelope verbatim, ≥6 entities/≥12 endpoints, OCC discipline, file split, lint) are satisfied.

## Step 3: Copy shared files — 2026-08-15T04:17:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1964_cut_sew_apparel_factory/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T04:34:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1964_cut_sew_apparel_factory/workspace/PRD.md` (367 lines). The withheld design-index files were not opened or referenced.

## What was generated

**Section list**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC & identity semantics, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified by containment check), 2.3 Pagination, 2.4 Common Resource Properties & Version Semantics, 2.5 Existence/Reference Validation, 2.6 Validation Order & Failure Precedence (11-step pipeline), 2.7 OCC (3 rules), 2.8 Units/Precision/Rounding, 2.9 Material Ledger Semantics (trim + fabric), 2.10 Segregation of Duties
- §3 Business Logic (8 subsections): 3.1 Styles/TechPacks/grading, 3.2 Domestic content & certification, 3.3 Trim & fabric intake, 3.4 Orders/planning/trim holds & sweep, 3.5 Markers/cutting/bundles, 3.6 Sewing floor (lines, assignments, piece work, WIP, line balance), 3.7 Payroll (pinned 5-step calculate), 3.8 Quality audits/AQL/rework loop (ends with order finish)
- §4 Endpoint table (4 columns, 61 rows), §5 Error catalogue (2 columns, 41 rows)

**Coverage**
- Entities: all 15 covered, with initial values, defaults, nullability, and per-field constraints in prose
- State machines: all 9 (incl. ProductionOrder's 3 parallel dimensions), all 44 transitions with preconditions, error IDs, and side effects
- Calculations: all 10 expressed as precise prose (size grading, marker allocation + gross/net utilization, trim grossing with per-line-ceiling ordering, piece-rate straight vs guaranteed-minimum variants, operator efficiency with 90/100 bonus tiers, payroll totals with pinned evaluation order, AQL plan tables, line balance, dual-basis domestic content with 0.70 threshold, WIP-by-SKU)
- Endpoints: 61/61 in §4 (method + path verified identical to scaffold); all side effects narrated in §3
- Errors: 41/41 mentioned in §2/§3 prose and tabulated in §5

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 104 required, 104 present, 0 missing
- endpoints[].request_body/input/path_params (endpoint-only set): 7 required, 7 present, 0 missing
- endpoints[].query_params: covered within the same set (limit, offset, all FK filters), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 41 checked, 41 expressed in prose (global pipeline in §2.6 + per-endpoint orders in §3), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (expected_style_version / expected_fabric_roll_version / expected_payroll_run_version, ERR_STALE_VERSION 412, checked-before-state), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (no pseudocode, no fuzzy words — verified by operator/fuzzy-word scan), 0 missing
- validations[] conditions: 41 checked, 41 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 61 checked, 61 expressed, 0 missing
- entities[].fields[] structured content: 104 checked, 104 reconstructible (defaults, null-until-stamped, enum spellings, ranges), 0 missing
- sibling-branch symmetry: 8 groups checked (APPROVE/REJECT, VERIFY/REJECT, PASS/FAIL QC, accept/reject audit, DRAFT/APPROVED cancel, 3-way rework-hold restore, gross/net, cost/unit bases), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 654
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Note for the caller: two verification subtleties were handled — the ``` fences inside the verbatim §2.2 block invert naive backtick pairing, so coverage was measured with fenced blocks stripped; and `### 3.1` headings contain the substring `## 3.`, so §3 extraction used line-anchored regex.

## Step 5: Generate Unit Tests — 2026-08-15T05:10:00.000Z

**Tests emitted: 109 total**
- **Queue A (Difficulty): 45 tests** — all 20 instances covered with ≥2 tests each.
- **Queue B (Corner): 64 tests** — all 24 non-stub instances covered with ≥1 test each. All 15 `excluded_because:` stubs verified to resolve to real difficulty instances and were not translated.

**Instances skipped (PRD-first filter): none dropped wholesale.** Two partial adjudications:
- `Corner/state_machines/bundle_created_in_ticketed_initial_state` — dropped the `version == 1` literal (PRD §2.4 never states the initial version value) and the exact `ticket_no` format value (PRD's `order_seq` "creation ordinal" is 0/1-base ambiguous); kept the PRD-pinned assertions (TICKETED, pre_rework_status null, completed_through_seq 0, qty/size/marker/order fields, non-empty unique ticket_no).
- The release-side trim-hold gate in `Corner/state_machines/start_cutting_blocked_by_trim_hold` is untestable via PRD-declared flows (bundles can only exist after start-cutting, which is itself hold-gated) — the instance is still covered by the start-cutting-side test; a comment in `test_05` documents the gap.

**Audits passed:**
- Tag audit: 109/109 tests carry exactly one `Design:` tag resolving to a real instance; queue-A ≥2 and queue-B ≥1 per instance; all stub cross-references resolve.
- PRD verbatim audit: every docstring contains an ≥8-word substring that survives literal grep of `workspace/PRD.md` (checked programmatically, 0 failures).
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code comments.
- `pytest --collect-only` collects 109 tests; all `test_helpers` imports resolve.

**test_helpers/ files**: `__init__.py`, `types.py` (15 entity TypedDicts + status/role enums), `api_client.py` (46 endpoint methods), `api_errors.py` (40 error IDs + status map registered with framework), `assertions.py` (per-entity assertions + fabric/trim ledger invariants), `factories.py`, `constants.py` (AQL tables, thresholds incl. END_LOSS_PCT/SPLICE_YARDS/HOURLY_GUARANTEE/bonus tiers/changeover buffer), `test_users.py` (shared headers incl. same-human cross-role pairs for SoD + `make_sewing_operator_headers` for entity-backed identity), `fixtures.py` (state-progression, approved-pack, planned-order-with-bundle, released-bundle-with-operator, completed-bundle, payroll-verified-entry, calculated-run, failed/rework-recorded audit, QC-passed-order composites).

**test_suite/ files**: `conftest.py`, `test_01_styles_and_tech_packs.py` (13), `test_02_domestic_content_and_certification.py` (7), `test_03_fabric_markers_cutting.py` (18), `test_04_production_orders_and_trim.py` (15), `test_05_bundles_and_piece_work.py` (13), `test_06_payroll.py` (14), `test_07_quality_audits.py` (15), `test_08_scheduling.py` (6), `test_09_computed_reads_and_envelope.py` (8).

## Step 6: Generate Implementation — 2026-08-15T05:10:00.000Z

**File list — `workspace/implementation/`**: `start.sh` (executable launcher), `requirements.txt` (`flask>=2.2,<4`), `app.py` (Flask entry point, Decimal-safe JSON provider, global request lock (serializes cascades), `ApiError`/404/405 envelope handlers, blueprint registration, binds `0.0.0.0:$PORT`), `db.py` (in-memory `Store` (15 entity dicts keyed by id, all empty at boot), strictly-increasing 3-fractional-digit UTC clock (guarantees `created_at` uniqueness relied on by payroll remainder allocation), order creation-ordinal counter), `errors.py` (`ApiError` + one factory per all 42 catalog error IDs with exact HTTP statuses), `response.py` (exact envelope: `meta.api_request_id` (`req_…`)/`api_request_timestamp`, `response_type`, `data`; list meta gains `limit`/`offset`/`total_count`/`has_more` (defaults 10/0, min 1, max 100)), `middleware.py` (`X-User-ID`/`X-User-Role` auth; 9 declared roles (`Any` is documentation-only, rejected as a header value); role authorization), `util.py` (Decimal-preserving body parsing, typed field validators, body-FK existence (before schema, per pipeline), shared `size_quantities` schema), `services/core.py` (`base_record` (version starts at 1), `touch` (version+1 + `updated_at`), lookups, FK getters), `services/calc.py` (all calculation rules), `routes/` — `styles.py`, `tech_packs.py`, `operation_specs.py`, `trim.py`, `fabric_rolls.py`, `production_orders.py`, `markers.py`, `bundles.py`, `sewing.py` (lines/assignments/operators), `piece_work.py`, `payroll.py`, `quality_audits.py`, `common.py` (list/pagination helper).

**Endpoint count: 61 (every row of the SCAFFOLD §1.5 table)**

**State machines implemented (10)**: Style (DRAFT→ACTIVE auto on first order; UNCERTIFIED/REVOKED→CERTIFIED; CERTIFIED→REVOKED auto-cascade on re-point losing QUALIFIED_STRICT), TechPack (DRAFT→PENDING_APPROVAL→APPROVED/REJECTED, REJECTED→DRAFT cyclic, APPROVED→SUPERSEDED auto), FabricRoll (RECEIVED→AVAILABLE/REJECTED; AVAILABLE→DEPLETED auto at `available_yards == 0` with the second version bump), ProductionOrder (3 parallel dimensions: PLANNED→CUTTING→SEWING→FINISHED; MATERIALS_OK↔TRIM_HOLD with all-or-nothing reservations + created_at-ASC receive sweep; QC_PENDING→QC_PASSED/QC_FAILED→REWORK_IN_PROGRESS→QC_PENDING rework cycle), Marker (DRAFT→APPROVED→CUT, DRAFT/APPROVED→CANCELLED with compensation), Bundle (TICKETED→RELEASED→IN_PROGRESS→COMPLETED plus REWORK_HOLD snapshot/restore of `pre_rework_status`), PieceWorkEntry (LOGGED→VERIFIED/REJECTED→PAID, incl. `reviewed_by_user_id='system'` auto-reject cascade), PayrollRun (OPEN→CALCULATED→APPROVED→PAID, CALCULATED→OPEN unwind loop clearing stamped entries), QualityAudit (OPEN→CLOSED_PASS/CLOSED_FAIL→REWORK_RECORDED→SUPERSEDED).

**Calculations implemented (10, all with Decimal, round-half-up at declared scale)**: size_grading (nearest 1/8", per-cell, negative steps), marker_allocation_and_utilization (gross/net variants, END_LOSS 2% + 0.5 splice), trim_grossing (per-line ceil before summation), piece_rate_earnings (straight + guaranteed-minimum variants, 1500¢/hr floor), operator_efficiency (tiers ≥100→10%, ≥90→5%, boundaries inclusive), payroll_run_totals (pinned 5-step order, pre-pay efficiency snapshot, pro-rata top-up/bonus shares with remainder to earliest `created_at`), aql_sample_plan (lot tiers, TIGHTENED bump capped at J, Ac/Re tables), line_balance (ceil takt, greedy in-sequence packing, oversized-op own station), domestic_content_determination (cost basis exact-decimal no ceil vs unit basis, pinned STRICT→COST_ONLY precedence, 0.70 threshold), wip_by_sku.

**start.sh confirmation**: executable, reads `$PORT` (default 10000), binds `0.0.0.0` (verified: Flask reports both 127.0.0.1 and the host's external IP), runs in the foreground via `exec python3 app.py`, and guards `pip install` behind `python3 -c "import flask"` so per-test reboots skip reinstall. Verified cold-boot: first boot creates and serves entities; a kill + fresh `bash start.sh` returns `total_count: 0` — state wipes completely, nothing seeded at startup. 100+ behavioral smoke assertions passed across 4 scripts covering auth/RBAC, validation precedence (OCC before state, safety before referential), all cascades, payroll math (top-up, 10% tier, remainder allocation), AQL plans, trim holds/sweep, roll depletion, and pagination.

## Step 7: Test-fix iteration loop — 2026-08-15T05:30:00.000Z

**Result: CLEAN 8-round parallel sweep — 109/109 passed in every round (results.1..8.json).**

Iterations run: 3 sweeps (sweep 2 was operator-terminated mid-run after root cause was already identified from its live monitor stream; failure detail confirmed via a targeted single-file rerun).

**Failures surfaced (sweep 1: 83/109 failing, identical across all 8 rounds — deterministic, not flaky):**
- All 83 traced to one upstream test_helpers bug: `TEST_USERS["any_headers"]` built `X-User-Role: Any`. PRD §2.1 declares `Any` "a pseudo-role used only in this document", and requests "presenting a role value outside the declared set" are rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Every read performed through `ANY` therefore received a PRD-correct 400.
- Sweep 2 (after the Any fix): 4 deterministic failures in test_07 (`test_aql_sample_plan_tiered_lookup_normal`, `test_aql_accept_at_accept_max_fail_at_reject_min`, `test_aql_verdict_updates_order_quality_status`, `test_reaudit_order_mismatch_rejected`) — all "Setup step failed: style_code must be unique": tests invoking two full setup chains in one test collided on the factories' fixed default `style_code` ("ST-1"), violating PRD §3.1's "a `style_code` (unique across all styles)".

**Tests deleted: none.** Every failing test traced to a verbatim PRD rule; both fixes were in test_helpers.

**Fixes applied to `test_helpers/`:**
- `test_users.py` — `any_headers` now uses a declared role (`PlantManager`, user `u-any1`) instead of the documentation-only pseudo-role `Any`; all uses are read-only endpoints, which PRD §2.1 opens to every authenticated role.
- `factories.py` — uniqueness-constrained defaults (`style_code`, `sku_code`, `roll_code`, `line_code`, `employee_no`) now get a process-unique suffix per call (`_uniq` over an itertools counter); explicit overrides unchanged.

**Fixes applied to `test_suite/`: none.**
**Fixes applied to `implementation/`: none** — the implementation was already PRD-faithful on every tripped rule (pseudo-role rejection, code uniqueness, all state machines, calculations, cascades, OCC).

## Step 8: Finalize PRD — 2026-08-15T05:45:00.000Z

Verification complete. `PRD_FINALIZED.md` is in place at `/home/ubuntu/github/CodingPRD/tasks/task_1964_cut_sew_apparel_factory/workspace/PRD_FINALIZED.md`, byte-identical to `PRD.md`.

**Line counts / delta:** `PRD.md` 367 lines, `PRD_FINALIZED.md` 367 lines — 0% delta (`diff` reports IDENTICAL). Zero edits were made; both Step 7 items verified as pure test-fixture bugs against behavior the PRD already pins verbatim.

**Changes:** none.

**Per-item verification log (in lieu of pre-edit search logs, since no edits were committed):**

- **Step 7 item 1 — `any_headers` pseudo-role fix (test_helpers/test_users.py).**
  - (a) Subject: whether `X-User-Role: Any` is a valid request header value.
  - (b) Paths enumerated: PRD §2.1 (PRD.md:15) — "`Any`, is a pseudo-role used only in this document... A request... presenting a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)"; impl `implementation/middleware.py:24-48` — `ALL_ROLES` lists exactly the nine declared roles, `authenticate()` raises `missing_context` (defined at `implementation/errors.py:21` as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400) when `role not in ROLES`; read endpoints marked `Any` in the PRD endpoint table are implemented as `require_roles(ALL_ROLES)` (e.g. `implementation/routes/styles.py:60,66`, `implementation/routes/quality_audits.py:87,97`, `implementation/routes/fabric_rolls.py:51`), matching PRD §2.1's "`Any` admits every authenticated role" (PRD.md:98).
  - (c) Outcome: PRD already determines the behavior word-for-word and implementation matches it exactly. No edit — any addition would restate §2.1 verbatim.

- **Step 7 item 2 — factories uniqueness fix (test_helpers/factories.py).**
  - (a) Subject: uniqueness constraints on `style_code`, `sku_code`, `roll_code`, `line_code`, `employee_no`.
  - (b) Paths enumerated: PRD §3.1 (PRD.md:139) — "a `style_code` (unique across all styles)"; §3.3 (PRD.md:171) — "a unique `sku_code`"; §3.4 (PRD.md:173) — "a unique `roll_code`"; §3.6 (PRD.md:205) — "a unique `line_code`"; §3.6 (PRD.md:209) — "a unique `employee_no`". Impl enforcement sites: `implementation/routes/styles.py:35` ("style_code must be unique across all styles"), `implementation/routes/trim.py:32`, `implementation/routes/fabric_rolls.py:30`, `implementation/routes/sewing.py:36` (line_code), `implementation/routes/sewing.py:176` (employee_no), all raised via `invalid_request` (`ERR_INVALID_REQUEST`, 400 — `implementation/errors.py:25`), the PRD's generic request-validation rejection (PRD.md:100, catalog entry PRD.md:330). The Step 7 failure ("Setup step failed: style_code must be unique") was tests colliding with this PRD-pinned constraint via fixed factory defaults — not a PRD silence.
  - (c) Outcome: PRD already declares uniqueness for all five fields; implementation enforces exactly that. The Step 7 fix was confined to test factories and revealed no PRD gap. No edit.

Per the run note, a byte-identical `PRD_FINALIZED.md` is the correct outcome here: Step 7 applied zero implementation fixes and zero test deletions, and both test_helpers fixes traced to rules the PRD already states verbatim and the implementation already follows.

## Step 9: PRD completeness scan — 2026-08-15T06:00:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1964_cut_sew_apparel_factory/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size delta:** PRD_FINALIZED.md 367 lines / 61,817 chars → PRD_COMPLETED.md 368 lines / 63,890 chars (+1 line, +2,073 chars; 21 in-place hunks, no new sections).

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions.

**Changes:**

- §2.1 — insert — ambiguity — pinned that `Any` is not a valid header value — implementation/middleware.py:36-47
- §2.4 — revise — ambiguity — pinned `version` starts at 1 at creation — implementation/services/core.py:17
- §2.6 — insert — ambiguity — pinned invalid/non-object JSON body → `ERR_INVALID_REQUEST`, and unknown body fields ignored — implementation/util.py:19-35
- §3.1 — revise — ambiguity — style create: duplicate `style_code` → `ERR_INVALID_REQUEST`; `size_run` non-empty with distinct labels — implementation/routes/styles.py:28-35
- §3.1 — insert — ambiguity — new style also starts with `certified_by_user_id` null — implementation/routes/styles.py:51
- §3.1 — insert — ambiguity — duplicate `version_no` (per style among non-SUPERSEDED packs) → `ERR_INVALID_REQUEST` — implementation/routes/tech_packs.py:67-71
- §3.1 — revise — ambiguity — graded-measurements cell shape (`point`/`size`/`value`) and emission order (points in `base_measurements` order, sizes in `size_run` order) — implementation/services/calc.py:41-55
- §3.3 — insert — ambiguity — duplicate `sku_code` → `ERR_INVALID_REQUEST` — implementation/routes/trim.py:31-32
- §3.3 — insert — ambiguity — duplicate `roll_code` → `ERR_INVALID_REQUEST` — implementation/routes/fabric_rolls.py:29-30
- §3.4 — revise — ambiguity — `size_quantities` must be non-empty — implementation/util.py:145-146
- §3.4 — insert — ambiguity — new order starts with `made_in_usa_eligible` null — implementation/routes/production_orders.py:59
- §3.4 — insert — ambiguity — planning an already-pinned order → `ERR_INVALID_STATE_TRANSITION` (409) — implementation/routes/production_orders.py:104-106
- §3.5 — revise — ambiguity — `order_seq` in `ticket_no` is the order's one-based creation ordinal across all orders — implementation/db.py:89-92, implementation/routes/markers.py:157
- §3.6 — insert — ambiguity — duplicate `line_code` → `ERR_INVALID_REQUEST` — implementation/routes/sewing.py:35-36
- §3.6 — insert — ambiguity — duplicate `employee_no` → `ERR_INVALID_REQUEST` — implementation/routes/sewing.py:175-176
- §3.6 — revise — ambiguity — line-balance read: `production_order_id` query param required (`ERR_INVALID_REQUEST`), order must exist (`ERR_NOT_FOUND`), order must have a pinned pack (`ERR_INVALID_REQUEST`) — implementation/routes/sewing.py:52-60
- §3.7 — insert — ambiguity — pro-rata allocation with an all-zero `piece_earnings_cents` pool sends the entire pool to the earliest-`created_at` entry — implementation/services/calc.py:189-193
- §3.7 — revise — **mismatch** — PRD claimed efficiency is "recomputed on entry verification and rejection… during the pay cascade"; impl never mutates the operator record at review time — revised to: derived on demand on every operator read and at calculate time, stored `efficiency_pct` refreshed only during the pay cascade — implementation/routes/piece_work.py:158-174, implementation/routes/sewing.py:162-166, implementation/routes/payroll.py:122-127
- §3.8 — insert — ambiguity — AQL lots outside the published tiers: below 2 → letter A, above 1200 → letter J — implementation/services/calc.py:308-310
- §3.8 — insert — ambiguity — verdict recording acts on the order/bundles only while `quality_status` is still `QC_PENDING`; otherwise the audit closes without cascading — implementation/routes/quality_audits.py:123-125,133-145
- §4 — insert — ambiguity — unmatched route → `ERR_NOT_FOUND` (404); unsupported method → `ERR_INVALID_REQUEST` body with HTTP 405 — implementation/app.py:49-57
- §5 — revise — **mismatch** — catalogue claimed to enumerate every error id but impl can emit `ERR_INTERNAL`; added lead-in clause and `ERR_INTERNAL` (500) table row — implementation/app.py:59-63

Everything else in the implementation (endpoint table, roles, OCC checkpoints, ledger math, grossing/ceiling order, AQL tables, guard-chain ordering, cascades, envelope shape, pagination) was already uniquely pinned by the PRD and left untouched.

---

**Pipeline complete.** All 9 steps finished; `workspace/PRD_COMPLETED.md` exists. Final test state: 109/109 passing across 8 parallel per-test-server rounds.
