# Worklog — task_1397_best_execution_trade_surveillance

## Step 1: Create task directory — 2026-08-13T03:28:00.000Z

Task directory `tasks/task_1397_best_execution_trade_surveillance/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; treated as DONE per instructions. Difficulty directive from user: "harder than expert level" — forwarded to scaffold generation as a target of the Expert band's upper bounds with maximum cross-entity coupling density (per scaffold skill §0.4, difficulty comes from coupling density, not volume).

## Step 2: Generate Scaffold — 2026-08-13T04:29:00.000Z

All three artifacts are written, parse cleanly, and pass `scaffold_lint.py` with a clean verdict (709 calls scanned, zero violations). No sibling task directories were consulted.

**Counts**

| Metric | Count |
|---|---|
| Entities | 15 |
| Endpoints | 53 |
| Validations | 30 (ordered, 8 categories) |
| State machines | 17 (Employee and SurveillanceCase each carry 2 parallel dimensions) |
| Calculation rules | 6 |
| Error codes | 37 |
| Roles | 7 (CoveredEmployee is `entity_backed:Employee`, rest opaque) |
| OCC concurrency rules | 3 |
| Difficulty-design instances | 18 (all active, all rule minimums met with differentiation) |
| Corner-design instances | 77 (68 active + 9 `excluded_because` stubs) |

**Notable coupling mechanisms**
- **Depth-3 transitive cascades from two different triggers**: (A) best-ex review publish → venue SUSPENDED → arrangement SUSPENDED → ROUTED orders CANCELLED (with conditional selectivity — EXECUTED orders untouched); (B) lexicon PATCH → QUEUED comm items rescored → score ≥ 100 auto-escalates → SurveillanceCase created. Reinstatement is deliberately asymmetric (venue reinstate does not restore arrangements/orders).
- **Parallel state dimensions with a cross-dimension gate**: SurveillanceCase `review_status × filing_status` — reopen is blocked while a filing is SUBMITTED (`ERR_FILING_IN_FLIGHT`), and reopen compensates by reverting alerts ESCALATED→ACKNOWLEDGED and voiding the draft filing. Employee `employment_status × attestation_status` gates preclearance independently.
- **Dual-variant calculations on different domains**: FAR_TOUCH vs MIDPOINT execution-quality benchmarks (asserted literals 2108.00/7.0033 vs −402.00/−1.3355) and MARGINAL vs RETROACTIVE PFOF tier evaluation (22500 vs 37500 on identical 150000-share volume).
- **Combinatorial formulas in two different modes**: (a) tiered PFOF with ≥3 inputs and nested min/max band allocation; (b) front-running score with pinned sum-then-round ordering where the forbidden order yields 24 instead of the correct 23.
- **Version-pinning on approval + OCC**: disclosures freeze venue lines and pin `arrangement_version` at submit; publish detects staleness (`ERR_DISCLOSURE_STALE`) with a withdraw/repin recovery cycle. OCC guards arrangement amend, disclosure revise, and lexicon retune (all 412-tested with strictly sequential stale-version calls).
- **Complementary boundary gates**: alert score 50 escalates / 49 closes; comm lexicon tiers at exactly 40/100; arrangement half-open adjacency vs restricted-list 86400s-buffer semantics (Rule 8 pair); late-filing fee at due+0s (0), +1s (50000), +1d (55000), +200d (cap 500000).
- **Derived-state reconciliation**: PROVISIONAL snapshots and DRAFT disclosures recompute on read; LOCKED/PENDING states freeze — both transitions tested against mutating source data.

**One deviation to flag**: endpoints landed at 53 rather than the 28–32 target. With 15 entities, the lint's FK reverse-reachability rule (every scalar FK needs a sub-resource or filtered-list GET) plus per-entity lifecycle actions set a floor well above 32; the subagent consolidated aggressively (single `transition` endpoints per entity, sub-resource reads under hub parents, no redundant single-GETs) and prioritized the directive's density/coupling goals over the endpoint band. This matches the skill's own precedent (its 14-entity example ships 64 endpoints).

## Step 3: Copy shared files — 2026-08-13T04:30:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1397_best_execution_trade_surveillance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T04:41:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1397_best_execution_trade_surveillance/workspace/PRD.md`.

**Output:** `workspace/PRD.md` — 320 lines, 8,396 words.

**Section structure:**
- **§1 Introduction** — 2 paragraphs (regulatory context, segregation-of-duties framing, `/surveillance` mount)
- **§2 Global Specifications** (10 subsections): 2.1 RBAC & identity semantics · 2.2 API Response Structure (byte-identical verbatim block, confirmed via string-containment check) · 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending) · 2.4 Logical Time & Epoch Sweeps (clock default 2026-08-01T00:00:00Z, monotonicity, ops-run tallies) · 2.5 Resource Identity/Timestamps/Change Tracking · 2.6 OCC (all 3 rules) · 2.7 Precision & Rounding · 2.8 Derived Fields / Recompute-on-Read / Freezing · 2.9 Cascades & Asymmetric Compensation · 2.10 Validation Evaluation Order
- **§3 Business Logic** (9 subsections): employees/attestation · venues/arrangements/orders · execution-quality snapshots · PFOF disclosures · committee reviews · personal-account trading · surveillance detection/cases/filings · comms review/lexicon · policies/training/restricted list
- **§4 Endpoint table** — 53 rows, 4 columns (Method, Path, Description, Authorized Roles); all 53 scaffold endpoints present
- **§5 Error catalogue** — 37 rows, 2 columns; all 37 scaffold errors present (scaffold header comment says 34 but the actual catalog lists 37)

**Coverage self-audit (all three hard contracts PASS):**
- **Contract 1 — Field-name coverage:** 95 required identifiers (15 entities' fields + common fields + all endpoint inputs/query params/path params), 95 present in backticks, 0 missing.
- **Contract 2 — Rule coverage:** validation priority ordering expressed globally (§2.10) and locally where gates stack (6-gate preclearance gauntlet, 4-gate routing); 3/3 OCC rules with write action + `expected_*_version` field + `ERR_STALE_VERSION`/412; all 17 state machines' transitions with preconditions and side effects (parallel Employee/SurveillanceCase dimensions, 3-link venue→arrangement→order cascade, lexicon rescore→escalate→case cascade, reopen compensation); all 5 calculations in precise prose with pinned rounding order (2dp lines / 4dp averages / integer scores, half-up everywhere) and constants embedded (3600s→"one hour (3,600 seconds)", 30 days→"2,592,000 seconds", 86400s buffer, 50000/5000/500000-cent late-fee tiers, 50/30/20 score weights, 25 bps trigger, 40/100 lexicon tiers, quorum of 3); all 37 validation conditions matchable to error IDs in §2/§3 prose; sibling-branch symmetry maintained (MARGINAL vs RETROACTIVE, FAR_TOUCH vs MIDPOINT, forward vs reverse front-running scans, APPROVED vs DENIED paths).
- **Contract 3 — §3 path purity:** 597 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — endpoints referenced only via state-pair framing, role+verb, or capability description.
- **RBAC:** all 7 role names spelled exactly; identity semantics translated (`CoveredEmployee` entity-backed by `Employee` with `ERR_NOT_RESOURCE_OWNER` ownership comparison; the six other roles opaque, with `created_by_user_id`/`voter_user_ids` recording noted).

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directories were inspected.

## Step 5: Generate Unit Tests — 2026-08-13T05:14:00.000Z

All checks pass. Generation complete.

**Test counts**
- Queue A (Difficulty): **36 tests** — all 18 instances in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` covered with exactly 2 tests each
- Queue B (Corner): **68 tests** — all 68 non-stub instances in `SCAFFOLD_CORNER_DESIGN.yaml` covered with exactly 1 test each
- **Total: 104 tests**, collected cleanly by pytest; all compile; pyflakes clean

**Instances skipped: none.** All 9 `excluded_because:` stubs in the corner index were verified to resolve to real difficulty-design instances (`state_beats_safety_on_denied_trade_decide`, `quality_benchmark_variants_diverge`, `review_publish_terminate_cascade_depth3`, `case_parallel_dimensions_with_cycles` ×2, `lexicon_retune_rescore_escalation_cascade`, `alert_score_boundary_50_escalate_vs_close`) and were not translated, per spec. Every translated assertion was found verbatim-covered in PRD.md (all 159 quoted docstring passages grep-verified against the PRD) and uniquely derivable.

**Helper module inventory** (`test_helpers/`)
- `types.py` — 28 status/role enums + 15 entity TypedDicts (all entities carry the four common fields per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with 44 methods covering all 54 PRD endpoints
- `api_errors.py` — `ApiErrorId` (37 codes) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — `assert_{entity}` for all 15 entities
- `factories.py` — 12 payload factories + `flat_tier` helper
- `constants.py` — thresholds from PRD (score 50 gate, 40/100 comm tiers, 25 bps trigger, late-fee schedule, quorum 3, 48h expiry, 30-day holding, 86400s buffer, default clock)
- `test_users.py` — shared headers for the 6 opaque roles + `make_covered_employee_headers(user_id)` entity-backed builder (+ per-instance analyst/committee builders)
- `fixtures.py` — composite setups: `setup_venue_with_active_arrangement`, `make_order` (create/route/execute), `setup_front_running_alert`, `escalate_alert_to_case`, `setup_case_under_investigation`, `setup_comm_case`, `make_review_in_committee`, `make_review_approved`, `make_lexicon_active`, `publish_policy`, `make_published_disclosure`, clock/ops-run helpers
- `test_suite/conftest.py` + 12 numbered test files grouped by domain concern

**Design decisions worth noting (PRD-faithfulness adjustments, not gaps)**
1. *Alert score-49 escalation test*: the design recipe attempted `ESCALATED` from `NEW`, but PRD §2.10 orders state admissibility before business gates and §3.7 admits escalation only from `ACKNOWLEDGED` — a faithful implementation would return `ERR_INVALID_STATE` there. The test acknowledges first so the score gate is genuinely the one under test, preserving the instance's boundary claim (`ERR_ALERT_SCORE_BELOW_ESCALATION` at 49).
2. *Timestamp assertions* (`decided_at`/`expires_at`/`reconciled_at`/`filing_due_at`/`current_utc`): PRD pins three-fractional-digit rendering only for `created_at`/`updated_at`, so equality is asserted on parsed datetimes (e.g. `expires_at == decided_at + 48h`) rather than string equality.
3. *List-order reliance* in the termination cascade and cascade tests was replaced with id-keyed lookups, since PRD's `created_at` ASC sort leaves same-timestamp tie order unspecified.

**PRD coverage gaps / judgment calls**
- No outright gaps forced a skip. One soft spot: PRD §2.5 says `version` "increments by exactly one on every mutation" but never states the initial value; two tests assert `version == 1` at creation / `== 2` after activation (per the design index's pre-computed literals, e.g. pinned `arrangement_version == 2`). This is the standard benchmark reading (creation = first mutation) but is the least-explicit literal in the suite.

## Step 6: Generate Implementation — 2026-08-13T05:22:00.000Z

Done. The implementation is complete and verified.

**File inventory (`workspace/implementation/`)**

| File | Purpose |
|---|---|
| `start.sh` | Foreground launcher; guarded dep install (`import flask` check, no-op when present), `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Flask wiring, blueprint registration, envelope-shaped error handlers (ApiError/404/405/500), binds `0.0.0.0:$PORT` (default 10000) |
| `core.py` | In-memory store (15 dicts, starts empty, zero seeding), logical clock (default `2026-08-01T00:00:00Z`), envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamp 1–100), auth (`X-User-ID`/`X-User-Role`, 7 roles), field/datetime validators |
| `services.py` | All 5 calculations, serializers, cascades, ops-run sweeps |
| `routes.py` | All 53 endpoints from the §1.5 table (scaffold header says 54 but the table enumerates 53; count verified against SCAFFOLD.yaml) |

**Endpoint count: 53/53 implemented**

**State machine / calculation / cascade coverage**

- **State machines**: all 17 machines including parallel dimensions — Employee (employment × attestation), SurveillanceCase (review × filing), plus Venue, RoutingArrangement, Order, Snapshot (lock), PfofDisclosure (submit/publish/withdraw/revise), BestExReview (with 3-vote auto-approve quorum and vote-clearing rework), SurveillanceAlert (ack/escalate/close with score gates at 50, case link-or-create selector), PersonalTrade, RestrictedListEntry (ops-run driven), CommReviewItem (auto-tier 40/100 at capture), LexiconPolicy, CompliancePolicy, TrainingAssignment. Terminal lockdown enforced everywhere.
- **Calculations**: `calc_execution_quality` (FAR_TOUCH/MIDPOINT, exact half-cent mid, pinned nested rounding: per-share 2dp → line 2dp → sum → avg 4dp, ROUND_HALF_UP via Decimal); `calc_pfof_accrual` (MARGINAL per-band rounding vs RETROACTIVE single-rate, per-group integer cents then summed, arrangement+version pinned from latest-executed group); `calc_front_running_score` (factors summed before single round, forward `[T-3600,T)` and reverse `(Pt,Pt+3600]` mirror windows); `calc_marking_close_score` (25 bps inclusive trigger, score=min(100, 2×dev)); `calc_lexicon_score` (case-insensitive substring, term counted once, null policy → 0/[]/null); `calc_late_filing_fee` (boundary-inclusive on-time, 50000 + 5000/day floor, cap 500000).
- **Cascades**: venue suspend → arrangements → routed orders (asymmetric reinstatement); best-ex publish TERMINATE_ROUTING three-link cascade; employee termination (deny pending / expire approved / cancel training); restricted-list activation denies pending preclearances; lexicon activate/retire/retune rescores QUEUED only with escalation-only (never down-tier); policy publish supersedes + training fan-out + stale-assignment compensation; case reopen compensation (alerts ESCALATED→ACKNOWLEDGED, case_id cleared, draft filing voided); disclosure publish supersedes prior PUBLISHED.
- **OCC**: all three guarded writes (`expected_arrangement_version`/`expected_disclosure_version`/`expected_lexicon_policy_version` → ERR_STALE_VERSION 412), checked before state admissibility per priority order; validation ordering follows §2.10 (auth → role+target → ownership → existence L-to-R → shape → uniqueness → clock → OCC → state → gates).
- **Derived fields**: snapshot metrics recompute on read while PROVISIONAL / frozen at LOCKED; disclosure `venue_lines` recompute while DRAFT / frozen+pinned at submit / unfrozen at withdraw; employee `open_case_count`/`training_overdue_count` recomputed per read.

**Boot confirmation**

`bash start.sh` boots cleanly from a fresh process and serves on `0.0.0.0:$PORT` (verified on the default 10000 and an explicit `PORT=18097`); the store is empty at boot and the clock reads `2026-08-01T00:00:00.000Z`. Three independent HTTP verification suites (~90 assertions covering happy paths, every calculation with hand-computed values, all cascades, error IDs/statuses, RBAC, pagination, and boundary conditions like the exact-86400s buffer gap, 30-day holding boundary, and score-50 alert gates) all pass with 0 failures.

## Step 7: Test/Fix Diagnostic Loop — 2026-08-13T05:55:00.000Z

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`) and iterated until clean.

**Iteration 1** — 11-test union of failures across 8 rounds (94-95/104 per round):
- 6 tests blocked by `TypeError: setup_venue_with_active_arrangement() got an unexpected keyword argument 'name'` (test_helpers bug).
- 2 tests failed setup with `ERR_EXECUTION_WINDOW_VIOLATION` (test setups issued executions outside PRD §3.2/§3.6 windows).
- 3 tests flaky "server could not be restarted" / transport resets under 8-way host contention.

**Fixes applied (all test-side; implementation needed none)**
1. `test_helpers/fixtures.py` — `setup_venue_with_active_arrangement()` now accepts and forwards `name` and `venue_type` to `make_venue` (PRD §3.2 venue creation fields; six tests in test_05/test_06 passed them and had never executed past setup).
2. `test_suite/test_04_execution_quality.py::test_execution_quality_month_window_half_open` — clock set to the boundary instants (23:59:59 / 00:00:00) so `executed_at` lies in `[created_at, now]` per PRD §3.2; assertion (half-open month window) unchanged.
3. `test_suite/test_08_cases_filings.py::test_alert_escalate_links_existing_open_case` — second trade's report moved from 14:30 to 14:52 (its `decided_at` was 14:50; PRD §3.6 closed `[decided_at, expires_at]` window) and matching order execution to 14:53; the front-running pairing and case-link assertions unchanged.
4. `test_suite/test_05_pfof_disclosures.py` — `_three_executed_50k` and `_setup_band_split` advance the logical clock to each execution instant before executing (latent §3.2 window violations unmasked by fix 1).
5. `test_helpers/api_client.py` — session now sends `Connection: close` so the per-test SIGKILL/respawn never leaves a stale keep-alive connection for the next test (eliminates `ConnectionResetError(104)` transport flakes; transport-only, no API-surface change).

**Implementation changes: none.** All failures traced to test artifacts or host contention; no PRD-required check was weakened; no tests deleted (every failing assertion traced verbatim to PRD).

**Iteration 2** — 2 real failures remained (band-split clock), plus 3 transport/boot flakes. Applied fixes 4-5.
**Iteration 3** — all 8 rounds 104/104. Removed temporary start.sh boot-logging instrumentation and re-ran the full 8-round sweep on the exact shipped state: **8/8 rounds clean, 104/104 each**.

## Step 7: Test-fix iteration loop — 2026-08-13T05:52:00.000Z

Final sweep: all 8 rounds clean, 104/104 each.

**Iterations run:** 3 sweeps of the 8-round parallel stability protocol (plus 1 solo diagnostic round). Final state: **8/8 rounds pass 104/104** on the exact shipped artifacts.

**Tests deleted:** None. Every failing assertion traced verbatim to PRD.md; no PRD-silence or unique-derivability collapses were found among the failures.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_venue_with_active_arrangement()` now accepts and forwards `name` and `venue_type` to `make_venue`. Six tests (test_05 pricing-variant/band-split cluster, test_06 review quorum/publish cascade) passed these PRD §3.2 venue fields but the fixture silently lacked the kwargs, so those tests had never executed past setup (TypeError). This is the triage-hint case: ≥5 failures sharing one helper defect.
- `api_client.py` — the shared session now sends `Connection: close`. The per-test-server harness SIGKILLs and respawns the server before every test; a pooled keep-alive connection was intermittently reused after the kill and failed mid-test with `ConnectionResetError(104)` (e.g. `test_one_second_less_gap_rejected`, round 7 of sweep 2). Transport-level only; no API-surface or assertion change.

**Fixes applied to `test_suite/` (all setup-clock corrections; assertions untouched):**
- `test_04_execution_quality.py::test_execution_quality_month_window_half_open` — setup executed order W1 at 23:59:59 while the logical clock read 12:00; the PRD §3.2 window (`created_at ≤ executed_at ≤ now`) correctly rejected it. Clock now advances to the boundary instant before each execution; the half-open-month assertion is unchanged.
- `test_08_cases_filings.py::test_alert_escalate_links_existing_open_case` — the second personal trade was reported at 14:30 while its own `decided_at` was 14:50 (clock had advanced), violating PRD §3.6's closed `[decided_at, expires_at]` report window. Report moved to 14:52 and the matching order execution to 14:53; front-running pairing and case-linking assertions unchanged.
- `test_05_pfof_disclosures.py` — `_three_executed_50k` and `_setup_band_split` executed orders at 12:30–12:40 with the clock at 12:00 (latent §3.2 violations unmasked once the fixture TypeError was fixed). The clock now rides along to each execution instant; all accrual math and assertions unchanged.

**Fixes applied to `implementation/`:** None. Root cause of every deterministic failure was a test artifact issuing requests inconsistent with PRD-mandated checks; the implementation's enforcement was correct and was not weakened. The intermittent "could not be restarted" setup failures were environmental (this host runs many concurrent benchmark pipelines; the runner's 15s boot-poll occasionally exhausts under load) and did not recur in the final two sweeps — no implementation or test change was warranted for them. Temporary boot-logging instrumentation added to `start.sh` for diagnosis was removed before the final confirming sweep.

## Step 8: Finalize PRD — 2026-08-13T06:00:00.000Z

All verification is complete. Determination: **zero edits** — every step_7 fix traces to behavior the PRD already uniquely determines, and the implementation matches the PRD at every site. PRD_FINALIZED.md stands as a byte-identical copy of PRD.md (created via `cp` in step 0, confirmed identical via `diff`).

**Line counts / %-delta:** PRD.md = 320 lines, PRD_FINALIZED.md = 320 lines — 0 lines changed, 0.0% delta. `diff` confirms the files are byte-identical.

**Changes:** None. No insertions, no revisions.

**Rationale per step_7_diff item (with the mandatory per-subject impl enumeration that a pre-edit search would require — here each search concluded "no edit," which is itself the outcome):**

1. **`fixtures.py` kwargs fix (venue `name`/`venue_type`)** — (a) Subject: venue creation fields. (b) Paths enumerated: `implementation/routes.py:155-168` (`create_venue` requires `venue_code` via `req_str`, `name` via `req_str`, `venue_type` via `req_enum` against `VENUE_TYPES`, duplicate code → `ERR_DUPLICATE_VENUE_CODE` 409); `test_helpers/fixtures.py:73-80,220-231` (the fixture bug itself). (c) PRD §3.2 already pins verbatim: "registers each execution venue with a unique `venue_code` ..., a display `name`, and a `venue_type` of `EXCHANGE`, `ATS`, or `MARKET_MAKER`." Implementation matches PRD exactly. Pure fixture bug, no PRD silence → no edit.

2. **`api_client.py` `Connection: close`** — (a) Subject: HTTP transport keep-alive between test harness and per-test-respawned server. (b) Paths enumerated: none in `implementation/` (transport header is harness-side; grep of implementation confirms no connection-management behavior). (c) Not an API-surface behavior; PRD is correctly silent → no edit.

3. **`test_04_execution_quality.py` clock fix** — (a) Subject: order-execution timestamp window. (b) Paths enumerated: `implementation/routes.py:436-450` (`if not (o["created_at"] <= ex_at <= now())` → `ERR_EXECUTION_WINDOW_VIOLATION` 422); the downstream consumers of `executed_at` — `services.py:76` (snapshot month scope `start <= ex_at < end`), `services.py:112` (covering arrangement window), `services.py:187,218,225,234,239` (front-running scan windows), `routes.py:568-570` (uncovered-volume check). (c) PRD §3.2 uniquely determines the closed window: "no earlier than the order's `created_at` and no later than the logical now ... rejected with `ERR_EXECUTION_WINDOW_VIOLATION` (HTTP 422)"; §3.3 pins the half-open month ("up to — but not including — the first instant of the next month"), matching `services.py:42-47,76`. All enumerated paths consistent with PRD prose → no edit.

4. **`test_08_cases_filings.py` clock fix** — (a) Subject: personal-trade execution-report window. (b) Paths enumerated: `implementation/routes.py:961-972` (`if not (t["decided_at"] <= ex_at <= t["expires_at"])` → `ERR_EXECUTION_WINDOW_VIOLATION` 422, then `reverse_front_running_scan`); the approval site stamping the window bounds at `routes.py:951-953` (`decided_at = now`, `expires_at = now + 48h`). (c) PRD §3.6 pins verbatim: "the reported `executed_at` must lie inside the closed window from `decided_at` through `expires_at`, both bounds inclusive (else `ERR_EXECUTION_WINDOW_VIOLATION`)" and "sets `expires_at` to the now plus 48 hours". Exact match → no edit.

5. **`test_05_pfof_disclosures.py` clock fixes** — (a) Subject: same §3.2 execution window plus §3.4 PFOF accrual scope. (b) Paths enumerated: `routes.py:440` (execution window), `services.py:50-56` (quarter window), `services.py:102-115` (covering arrangement), `services.py:118-160` (tier evaluation MARGINAL/RETROACTIVE, per-group round-half-up then summation), `routes.py:568-570` (submit-time `ERR_UNCOVERED_VOLUME`). (c) PRD §3.2 and §3.4 pin all of this (half-open quarter windows, per-group rounding before summation, pinned line-selection by latest execution). No divergence → no edit.

6. **Implementation fixes: none applied by Step 7** — Step 7 explicitly reported "no PRD-silence or unique-derivability collapses were found among the failures," and the subagent's independent read of the five enforcement sites above confirms implementation behavior is uniquely determined by existing PRD prose at every one.

**Deliverable:** `workspace/PRD_FINALIZED.md` — byte-identical to PRD.md. A fresh implementer reading it produces the shipped behavior because every Step 7 failure was a test artifact violating PRD-mandated checks, not a PRD ambiguity; the PRD already pins each contested behavior (closed `[created_at, now]` execution window, closed `[decided_at, expires_at]` report window, required venue `name`/`venue_type` fields).

## Step 9: Complete PRD — 2026-08-13T06:14:00.000Z

Done. `PRD_COMPLETED.md` is written at `workspace/PRD_COMPLETED.md` with 14 minimal inline changes, all verified against the implementation.

**Source vs output:** PRD_FINALIZED.md — 320 lines / 62,121 chars; PRD_COMPLETED.md — 322 lines / 63,733 chars. Char-delta: **+1,612**.

**Counts:** 13 ambiguity-pins, 1 mismatch-revision.

**Changes (one per bullet):**

- §2.1 — insert — ambiguity — pinned that `X-User-ID` is never separately validated and its absence is never grounds for rejection (only the role header gates 401) — `implementation/core.py:136-140`
- §2.2 — insert — ambiguity — pinned that `api_request_timestamp` is rendered from the logical clock, not wall-clock — `implementation/core.py:86-88`
- §2.2 — insert — ambiguity — pinned that undefined paths and unsupported methods on defined paths are rejected with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope — `implementation/app.py:19-26`
- §2.3 — insert — ambiguity — pinned pagination enforcement style: out-of-range `limit`/`offset` are clamped (1/100/0), non-integer values fall back to defaults, never rejected — `implementation/core.py:104-123`
- §2.3 — insert — ambiguity — pinned list sort tie-breaking: stable sort, `created_at` ties retain creation order — `implementation/core.py:126-128`
- §2.5 — insert — ambiguity — pinned initial `version` = 1 at creation and `created_at` == `updated_at` at creation — `implementation/core.py:221-223`
- §2.5 — insert — ambiguity — pinned that request-body timestamps honor any ISO 8601 offset and offset-less timestamps are read as UTC — `implementation/core.py:70-82`
- §2.6 — insert — ambiguity — pinned that in the three OCC writes, an optional field supplied with null is treated as omitted — `implementation/routes.py:327-340,1112-1116`
- §2.10 — insert — ambiguity — added "a body that fails to parse as a JSON object" to the request-shape error category — `implementation/core.py:168-179`
- §3.2 — revise — ambiguity — `pfof_tiers` rule tightened from "sorted ascending" to non-empty, strictly ascending, duplicate thresholds rejected, thresholds non-negative — `implementation/routes.py:218-238`
- §3.4 — insert — ambiguity — pinned `venue_lines` response ordering: ascending by `venue_id` — `implementation/services.py:171`
- §3.4 — revise — mismatch — replaced the false claim "because arrangement windows for a venue never overlap, at most one arrangement covers any instant": the §3.2 overlap rule ignores terminated arrangements, so a reused window can produce multiple covers; pinned the impl's tie-break (latest `effective_from` wins) — `implementation/services.py:102-115`
- §3.4 — insert — ambiguity — pinned that an executed order with no covering arrangement contributes nothing to the accrual and instead blocks submission via the coverage gate — `implementation/services.py:150-152`
- §3.8 — insert — ambiguity — pinned that a terms-only retune of the currently `ACTIVE` lexicon policy triggers the same QUEUED-item rescore cascade, while retuning a `DRAFT` policy's terms rescores nothing — `implementation/routes.py:1141-1143`

Everything else in the implementation — all 47 endpoints, state machines, the detection formulas, rounding orders, sweep tallies, gate evaluation orders, cascades, OCC points, and serializer field sets — was checked and found already uniquely pinned by the PRD, so no further changes were made.
