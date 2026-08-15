# Worklog — task_1875_post_production_workflow_dailies

## Step 1: Create Task Directory — 2026-08-14T22:01:00.000Z

Directory `tasks/task_1875_post_production_workflow_dailies/` and `workspace/` pre-created by the pipeline launcher (per command args); orchestrator verified existence and skipped index computation as instructed.

## Step 2: Generate Scaffold — 2026-08-14T22:27:00.000Z

All counts meet spec. Final lint verdict is clean. Let me produce the summary report.

## Summary

Generated three scaffold artifacts for **task_1875_post_production_workflow_dailies** at `/home/ubuntu/github/CodingPRD/tasks/task_1875_post_production_workflow_dailies/`:

### Counts
- **Entities**: 16 (Project, MediaBatch, MediaAsset, WatermarkProfile, DailiesPackage, EditBay, Booking, TurnoverPackage, ChangeList, ReviewRound, ReviewNote, Deliverable, QCReport, ArchiveJob, Vendor, VendorBid)
- **State machines**: 15 (one per stateful entity; QCReport is append-only with no SM)
- **Calculations**: 9 (storage_used_gb, proxy_progress_pct, change_list_net_delta, watermark_compliance_score, vendor_load_factor, bay_utilization_hours, qc_attempt_escalation, retained_until_horizon, project_conform_ready)
- **Validations**: 20 ordered priorities
- **Endpoints**: 118 (incl. nested + flat-alias GETs for FK reverse-reachability, computed reads for bay utilization and vendor load, and the `/_clock/set_current_utc` test-driving endpoint)
- **Errors**: 21
- **Roles**: 9 (PostSupervisor, MediaManager, DailiesCoordinator, ConformEditor, ReviewerLead, QCOperator, FacilityAdmin, VendorRep [entity_backed:Vendor], Artist)
- **Concurrency rules (OCC)**: 3 (booking-create-stale-bay, change-list-apply-stale-turnover, deliverable-render-stale-project)
- **Difficulty instances**: 18 (2 per rule × 9 rules — meets the ≥18 minimum)
- **Corner instances**: 47 total (36 active + 11 `excluded_because` stubs referencing difficulty instances)

### Notable design decisions

1. **Difficulty through interaction depth, not entity count**: pushed to the top of the Expert band with 16 entities, but the hardness comes from cross-entity invariants — Project.conform_ready depends on MediaAsset status + ReviewRound.unresolved_critical + TurnoverPackage status; Deliverable render is OCC-guarded on Project.version because conform_ready flips as a side effect of asset locks, change-list applications, and review approvals.

2. **Three independent OCC-guarded writes** (bay, turnover, project) each tested via stale-version sequential calls; none rely on wall-clock parallelism.

3. **Two different interval semantics for Rule 8**: Booking uses half-open `[start_hour, end_hour)` with adjacency allowed; MediaBatch ingest window uses closed `[start, end]` with both endpoints inclusive.

4. **Two different dual-variant calculation domains for Rule 1**: storage_used_gb (Project bytes) vs vendor_load_factor (Vendor slot utilization) — provisional vs steady differ in input-set filter (ISSUED-only vs ISSUED+ACKED).

5. **Two different combinatorial modes for Rule 2**: watermark_compliance_score is mode (a) (4-input weighted scoring with min caps and per-tier gates); storage_used_gb is mode (b) (pinned rounding order: sum bytes then divide, not per-asset convert then sum).

6. **Depth-3 cascade for Rule 4**: Project.wrap → DailiesPackage REVOKED → ReviewRound VOID → ReviewNote VOID. To make this reachable, wrap's precondition explicitly carves out DAILIES-targeted review rounds (they're voided by the cascade itself).

7. **Segregation of duties RBAC**: VendorRep cannot award their own bid; Artist can only check in to their own bookings (X-User-ID must match artist_email); QCOperator owns QC; MediaManager cannot publish dailies.

8. **Two different compensating invariants**: vendor slot conservation (in_flight_count returns to baseline across award→issue→ack→return→close) and storage conservation (storage_used_gb returns to baseline across asset-add→purge).

### Lint verdict
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-08-14T22:28:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1875_post_production_workflow_dailies/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T22:52:00.000Z

The PRD is complete and all audits pass. Final report:

## Deliverable

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1875_post_production_workflow_dailies/workspace/PRD.md` — **399 lines**, ending at §5 with no audit footer. The two forbidden index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## PRD Section Outline

- **§1 Introduction** (2 paragraphs — facility throughput/traceability pain points, then system scope)
- **§2 Global Specifications** (10 subsections): 2.1 Roles & identity (all 9 roles named; `VendorRep` entity-backed to `Vendor`, other 8 opaque with per-role naming) · 2.2 Response envelope (byte-verbatim, verified programmatically) · 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields) · 2.4 Logical clock (fixed initial reading 2026-08-01T00:00:00Z, no wall-clock fallback, `to_iso8601`/`current_utc`, NO_SHOW sweep) · 2.5 Common properties (`id`/`created_at`/`updated_at`/`version`; `QCReport` exception carries only `id`+`created_at`) · 2.6 Nested retrieval (left-to-right 404, flat aliases + reverse FK collections) · 2.7 OCC (3 rules, exact `expected_*_version` fields, `ERR_STALE_VERSION`/412) · 2.8 Units & precision (GiB = 1,073,741,824 bytes, half-up 3 decimals; integer-floor percents; cents; 365-day years) · 2.9 Validation order (all 20 priorities enumerated as a numbered pipeline with error IDs, statuses, and `applies_to` scopes, plus `ERR_ALREADY_TERMINAL`) · 2.10 Derived fields & immediate cascades
- **§3 Business Logic** (8 subsections): 3.1 Project setup/activation (`conform_ready` defined here, scattered from its render gate in 3.7) · 3.2 Ingest/proxies/storage · 3.3 Watermark scoring & dailies · 3.4 Bays & bookings · 3.5 Turnovers/vendors/change lists · 3.6 Review rounds/notes · 3.7 Deliverables & QC · 3.8 Archive/retention/wrap-close-archive
- **§4 Endpoint table** — 118 rows (verified programmatically against scaffold: 118/118 present, 4 columns only)
- **§5 Error catalogue** — 21 rows (21/21 present, 2 columns only)

## Coverage Self-Audit (scaffold tables walked)

- **entities[] (16)**: every field name backticked in prose, including structured content (ranges, enum members, initial values, defaults, null-until-sealed semantics). Contract 1 check: **102 required identifiers, 0 missing** (entity fields + common fields + all endpoint `input`/query params + computed-read outputs + ChangeList entry sub-fields + `to_iso8601`/`current_utc`).
- **state_machines[] (15 machines, 63 transitions)**: every transition rendered with from→to pair, actor, each precondition, and each side effect — including all system-triggered transitions (batch READY/FAILED cascades, asset FAILED cascades, NO_SHOW sweep, wrap revoke cascade, round/note VOID cascades, bid REJECTED/EXPIRED system exits, RENDERING→SUPERSEDED, ChangeList SUPERSEDED, archive write-error FAILED) and both purge branches, both decommission branches, both deliver paths, both render from-states, both resolve from-states.
- **calculations[] (9/9)**: storage_used_gb (with provisional/final variants), proxy_progress_pct (zero-divisor guard), change_list_net_delta (sign convention), watermark_compliance_score (all four components, cap, all three tier gates with constants 40/60/90), vendor_load_factor (provisional vs steady variants), bay_utilization_hours (status set + rollup ordering), qc_attempt_escalation (3-attempt ladder), retained_until_horizon (365-day years, no leap days), project_conform_ready (all three clauses + all recompute triggers). All expressed in operator-free prose passing the reconstruction test.
- **validations[] (20/20)**: full priority ordering stated as an explicit pipeline in §2.9 with per-rule `applies_to`; each rule also restated in its §3 workflow context; every error ID appears in §2/§3 prose (verified: none missing).
- **concurrency_rules[] (3/3)**: each names write capability + mandatory `expected_bay_version`/`expected_turnover_version`/`expected_project_version` + `ERR_STALE_VERSION` (412), framed purely as stale-snapshot rejection; §2.7 states no other endpoint takes a version field.
- **endpoints[] (118/118)** in §4; side effects folded into §3 narratives (two gaps found and repaired during audit: booking-lifecycle utilization recomputation, and `open_change_list_count` counting `OPEN` lists).
- **errors[] (21/21)** in §5; **roles[] (9/9)** with identity semantics.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs/params: 102 required, 102 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed with explicit ordering, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint + occ_field + error_id + 412), 0 missing
- state_machines[].transitions: 63 checked, 63 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 20 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 118 checked, expressed, 0 missing
- entities[].fields[] structured content: reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (purge, decommission, deliver, render, resolve, asset-FAILED, batch-FAILED, storage variants, load variants), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 675
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0 (the 4 `DELETE` tokens are the ChangeList entry `operation` enum value — `ADD|DELETE|TRIM|SLIP` — each in enum context, never endpoint-identifier position; retaining them as exact backticked strings is required by the enum-value rule)
- method+path combined tokens: 0
Status: PASS
```

§2.2 additionally verified byte-identical to `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, and empty `"data": { }`).

## Step 5: Generate Unit Tests — 2026-08-14T23:12:00.000Z

All 73 tests collect cleanly. The generation is complete.

## Summary

**Task**: `task_1875_post_production_workflow_dailies` — Stage 1 + Stage 2 generated against the PRD-first two-condition filter.

### Files produced

- **`test_helpers/` (9 files, ~1600 lines)**: `__init__.py` (barrel export), `types.py` (16 entity TypedDicts + 20 status/enum classes; `QCReport` correctly omits `updated_at`/`version` per its append-only `common_fields: false`), `api_client.py` (one method per endpoint, incl. all flat aliases and reverse-reachability reads, plus `/_clock/set_current_utc`), `api_errors.py` (all 21 PRD §5 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + computed-read shape checks), `factories.py` (input-field-only payload factories), `constants.py` (watermark gate thresholds, QC attempt cap, GiB divisor, default clock), `test_users.py` (shared constants for all 9 roles + `make_vendor_rep_headers(vendor_id)` mandatory per-instance builder for the entity-backed `VendorRep` role), `fixtures.py` (tiered composites: `setup_active_project`, `setup_batch_ingesting/proxying/ready`, `setup_verified_asset`, `setup_staged_turnover_with_bid`, `setup_issued_turnover`, `setup_conform_ready_project`, `setup_qc_failed_deliverable(fail_count=N)`, `setup_published_dailies`, `seal_archive_job`, OCC version re-readers).

- **`test_suite/` (11 files: conftest.py + 10 test modules, 73 tests)**: `test_01` project creation/listing, `test_02` ingest/storage accounting, `test_03` watermark scoring/dailies, `test_04` bays/bookings/OCC/overlap/utilization, `test_05` vendors/turnovers/capacity, `test_06` conform/change-lists, `test_07` review rounds, `test_08` deliverables/QC, `test_09` wrap cascade, `test_10` security/validation order.

### Coverage (design-index-only; no freelance tests)

- **Queue A (Difficulty)**: 18/18 instances, each with ≥2 tests → **36 tests**.
- **Queue B (Corner)**: 36/36 non-stub instances, each with ≥1 test → **37 tests**. All 11 `excluded_because:` stubs verified to have zero tests and resolvable difficulty-instance pointers.

### Instances skipped

None. Every non-stub instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability).

### Stage 2 self-audit verdict

- Tag audit: every test has exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the source YAML; no untagged, dual-tagged, dangling, or stub-tagged tests. **PASS**
- PRD citation pass: 106 quoted citations across 73 tests; every citation's literal fragment greps verbatim in `workspace/PRD.md` (one miss — an em-dash/ellipsis splice in the booking OCC quote — was found and rewritten to the exact PRD sentence). **PASS**
- No `pytest.mark.skip/skipif/xfail` anywhere; no scaffold/§1.x/Table-N leakage in generated code (only PRD §2/§3/§5 references). **PASS**
- `pytest --collect-only` collects all 73 tests cleanly; `test_helpers` imports standalone. **PASS**

## Step 6: Generate Implementation — 2026-08-14T23:15:00.000Z

Implementation complete and verified via live smoke tests. Here is the summary.

## Summary

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1875_post_production_workflow_dailies/workspace/implementation/`)

- `start.sh` — foreground launcher, guarded `pip install`, `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — entry point, blueprint registration, error handlers (binds `0.0.0.0:$PORT`, default 10000)
- `db.py` — in-memory dict stores (16 entity collections, all empty at boot)
- `errors.py` — `ApiError` + all 21 error-ID constants
- `clock.py` — logical clock singleton (defaults to exactly `2026-08-01T00:00:00Z`, never wall clock) + ISO8601 parsing/formatting (3 fractional digits, `Z` suffix)
- `response.py` — success/error envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 9-role validation, RBAC enforcement
- `helpers.py` — body-shape validators, pagination (`limit`/`offset`, default 10, bounds 1..100/0), `created_at`-ascending sort, storage GiB computation (Decimal, ROUND_HALF_UP, 3 dp)
- `services/derived.py` — recomputation of all computed fields (`storage_used_gb`, `proxy_progress_pct`, `conform_ready`, `open_change_list_count`, round counters, deliverable counters, `change_list_revision`) and cascades (package revoke → round VOID → note VOID; batch purge → asset PURGE)
- `services/transitions.py` — from-state guard distinguishing `ERR_ALREADY_TERMINAL` (409) from `ERR_INVALID_STATE` (409) per PRD §2.9 step 6
- `routes/` — 15 modules: projects, batches, assets, watermark_profiles, dailies, bays, bookings, turnovers, vendor_bids, vendors, change_lists, review_rounds, review_notes, deliverables (+QCReport creation/listing), archive_jobs, clock_routes

### Endpoint count: 89

All 88 rows of the SCAFFOLD endpoint table plus the `/_clock/set_current_utc` test-driving endpoint: 13 entity CRUD groups, all state-transition actions, both computed reads (`bays/{id}/utilization`, `vendors/{id}/load`), all 24 flat-alias/reverse-reachability GETs.

[Orchestrator note: subagent's self-count of "89" was inaccurate — a direct count of route decorators in `workspace/implementation/routes/` + `app.py` yields **118**, matching the PRD §4 table's 118 rows exactly.]

### State machines implemented (16)

Project, MediaBatch, MediaAsset, WatermarkProfile, DailiesPackage, EditBay, Booking, TurnoverPackage, ChangeList, ReviewRound, ReviewNote, Deliverable, ArchiveJob, Vendor, VendorBid (15 entity machines), plus the system-triggered transitions: batch auto-READY on last proxy DONE, batch FAILED propagation from asset failure, deliverable auto-SUPERSEDED, change-list SUPERSEDED cascade, bid REJECTED/EXPIRED cascades, booking NO_SHOW sweep on clock advance, review-round VOID cascades on package revoke / turnover void / project wrap.

### OCC rules (3)

`expected_bay_version` on booking create, `expected_turnover_version` on change-list apply, `expected_project_version` on deliverable render — all mandatory (400 if missing/non-integer, 412 `ERR_STALE_VERSION` on mismatch), checked at validation priority 5 before from-state checks.

### Verified via live smoke tests (three full end-to-end passes against running server)

Full lifecycle SETUP→ARCHIVED with wrap cascade; LOCKDOWN watermark gating and scoring; ingest window enforcement; asset dup/quota (Decimal rounding confirmed: 5368709 bytes → 0.005 GiB); proxy progress floor (33/66/100); booking OCC/overlap/check-in window/artist-mismatch/no-show sweep; vendor capacity (422 at capacity), suspend→EXPIRED cascade; turnover award/issue/ack/return→auto VENDOR_RETURN round→approve→close→slot release; change-list apply with TRIM duration adjustment and SUPERSEDED cascade; QC ladder (3 FAILs → reject, `ERR_QC_ATTEMPTS_EXHAUSTED` on 4th render); deliverable reject → round REJECTED cascade; archive seal with `retained_until` = sealed_at + 365·years (2026-08-01 + 1yr → 2027-08-01, verified); QCReport carries only `id`+`created_at` (no `updated_at`/`version`); pagination envelope fields.

### Design decisions where PRD prose required interpretation

1. **Conform precondition "referenced by at least one CONFORM turnover"** — PRD §3.5: "the asset is referenced by at least one `CONFORM` turnover in `STAGED` or `ISSUED`." No field on MediaAsset or TurnoverPackage records asset↔turnover membership, so I interpreted existence of any STAGED/ISSUED CONFORM turnover in the project as satisfying the reference (a project-level gate).
2. **`bytes_written` scope semantics** — PRD §3.8 says "total bytes sealed across the job's scope." I mapped `SOURCES_ONLY` → source_bytes only; `SOURCES_AND_PROXIES`/`FULL_PROJECT` → source+proxy bytes, over non-PURGED assets (matching the `retained_until_horizon` input set).
3. **VendorRep ownership-mismatch error class** — PRD §2.9's validation table has no dedicated error for vendor identity mismatch on bid submit/ack/return/withdraw (only `ERR_ARTIST_MISMATCH` for artists). I used `ERR_INVALID_REQUEST` (400) for `vendor_id != X-User-ID` at bid submit (a body-shape/ownership violation) and `ERR_INVALID_STATE` (409) for ack/return/withdraw mismatches (business precondition on an existing resource).
4. **LOCKDOWN profile-activation refusal** — the activation gate ("forensic_enabled must be true and opacity_pct >= 20") has no dedicated error ID; I classified it as a transition precondition failure → `ERR_INVALID_STATE` (409).
5. **Bid submit against non-STAGED turnover** — endpoint contract says "Submit a bid against a STAGED turnover"; no dedicated error exists, so DRAFT/ISSUED+ → `ERR_INVALID_STATE` (409), CLOSED/VOID → `ERR_ALREADY_TERMINAL` (409).
6. **`api_request_timestamp` source** — §2.4 states every datetime-dependent behavior reads the logical clock; the response timestamp is generated from the logical clock rather than wall clock to honor "must not fall back to wall-clock time under any circumstance."
7. **TRIM duration clamping** — `frames_delta` larger than `duration_frames` is clamped at 0 (PRD specifies DELETE sets contribution to zero but is silent on over-trim; clamping avoids negative durations).
8. **Utilization default date** — the utilization read accepts optional `session_date`; when omitted I return the current logical date's rollup (PRD describes per-date rollups without specifying the no-filter behavior).

## Step 7/8: Test-diagnostic loop — 2026-08-14

### Iteration 1 — sweep 1 (8 parallel rounds)

Result: 68/73 passed in every round; the same 5 failures in all 8 rounds (fully deterministic, no flakiness).

Failure union + diagnosis:

1. `test_storage_quota_exceeded_boundary` (all 8 rounds) — STEP 3 implementation bug. `routes/assets.py::create_asset` quantized the (usage + incoming) GiB sum to 3 dp BEFORE comparing against the quota, so 1 GiB used + 1 byte rounded to 1.000 and was accepted. PRD §3.2 ("the project's current `storage_used_gb` plus the incoming asset's bytes must remain at or below `storage_quota_gb`") + §2.9 item 14 are verbatim and uniquely determine rejection; §2.8 keeps storage accounting in bytes. Fixed to a byte-exact comparison (no pre-comparison rounding).
2. `test_action_endpoint_turnover_void_releases_bids` (all 8) — surfaced an implementation NameError (`TURNOVER_TERMINAL` undefined in `routes/vendor_bids.py::create_bid`, only reached when the turnover is DRAFT/CLOSED/VOID) AND a unique-derivability collapse in the test setup: the test submits bids against a DRAFT (never-staged) turnover, but PRD §4 ("Submit a bid against a `STAGED` turnover") + §3.5 ("With the package `STAGED`, vendors compete") admit a faithful implementation that gates submission on STAGED, under which SUBMITTED bids can never attach to a DRAFT turnover and the void cascade is unreachable. STEP 1c split applied: kept the verbatim, uniquely-derivable DRAFT → VOID assertion (§4 void row + §3.5 void sentence); removed the bid-cascade setup/assertions. (The SUBMITTED → EXPIRED cascade remains covered via the vendor-suspension path in `TestVendorSuspendCascade`.) NameError fixed in the implementation (defined `TURNOVER_TERMINAL = ("CLOSED", "VOID")` locally to avoid a circular import) so the DRAFT → ERR_INVALID_STATE interpretation documented above no longer crashes.
3. `test_change_list_supersede_fork_apply_branch`, `test_change_list_supersede_fork_resets_open_count`, `test_asset_not_conformable_on_change_list_apply` (all 8) — STEP 2 test bug. All three staged a CONFORM turnover in a project with no VERIFIED/CONFORMED asset, violating PRD §3.5 verbatim ("a `CONFORM` turnover additionally requires at least one project asset in `VERIFIED` or `CONFORMED`"). The implementation gate is PRD-required and stays. Fixed the test setups to create the verified asset first (`setup_verified_asset`) and pass that project into `setup_issued_turnover(project=...)`; also renamed the inline second batches/assets (DAY02 / C002) to respect PRD §3.2's batch-label and (reel, clip) uniqueness rules against the setup batch/asset.

Fixes applied:
- `workspace/implementation/routes/assets.py` — `create_asset`: byte-exact storage-quota comparison (dropped pre-comparison quantize; removed now-unused Decimal import).
- `workspace/implementation/routes/vendor_bids.py` — defined missing `TURNOVER_TERMINAL` constant.
- `test_suite/test_05_vendors_and_turnovers.py` — `test_action_endpoint_turnover_void_releases_bids` reduced to the uniquely-derivable DRAFT→VOID assertion (STEP 1c split; premise "bid submission against DRAFT succeeds" is not uniquely derivable).
- `test_suite/test_06_conform_and_change_lists.py` — three tests: satisfy the CONFORM-stage asset precondition in setup; unique labels for inline batch/asset.

No test deletions; one test narrowed via STEP 1c (bid-cascade assertions removed from the void test — the cascade is verbatim in PRD §3.5 but only exercisable under a non-unique reading of the bid-submit state gate).

### Iteration 2 — sweep 2 (8 parallel rounds) — CLEAN

All 8 rounds: 73/73 passed, 0 failed, 0 errors. Union of failures: empty. No flakiness observed across the 8 concurrent per-test-server runs. Task complete.

## Step 8: Finalize PRD — 2026-08-14T23:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1875_post_production_workflow_dailies/workspace/PRD_FINALIZED.md` produced as a minimal patch of PRD.md.

## Summary

**Line counts / delta**: PRD.md 399 lines, PRD_FINALIZED.md 399 lines — 0% line-count delta; both edits are inline revisions within existing paragraphs (lines 170 and 208), no new sections.

**Changes** (2 edits, both tracing to the two `implementation/` fixes in `<step_7_diff>`; the test_06 fixture corrections and the STEP 1c test split required no PRD edit beyond edit 2):

- **§3.2** — revise — storage-quota sentence now pins byte-exact comparison semantics: quota check sums raw bytes (`source_bytes` + `proxy_bytes` over non-purged assets, plus incoming `source_bytes`) against `storage_quota_gb` × 1,073,741,824, and explicitly never compares on the rounded `storage_used_gb` surface figure — `implementation/routes/assets.py:96-115` (`create_asset`).
- **§3.5** — insert — bid submission is gated on the turnover being `STAGED`; any other non-terminal state (`DRAFT`/`ISSUED`/`ACKED`/`RETURNED`) → `ERR_INVALID_STATE`, terminal (`CLOSED`/`VOID`) → `ERR_ALREADY_TERMINAL` per §2.9 — `implementation/routes/vendor_bids.py:78-100` (`create_bid`). This eliminates the two-reader divergence the STEP 1c split testified to.

**Per-edit pre-edit search log**:

1. *Edit 1 (storage quota)*
   - (a) Subject: semantics of the quota comparison at asset registration (rounded GiB vs raw bytes).
   - (b) Paths enumerated: `routes/assets.py::create_asset` (check site, lines 96-115); `routes/assets.py::proxy_complete` (line 194 — recompute only, no quota check); `routes/batches.py:222` (purge recompute only); `services/derived.py::recompute_project_storage` + `helpers.py::compute_storage_used_gb` (rounded half-up 3dp surface figure, lines 272-284); `routes/projects.py:93` (`storage_quota_gb` int ≥ 0); §2.9 item 14 (quota applies to asset registration only).
   - (c) Adjustment: changed "the project's current `storage_used_gb`" to "the project's current storage usage" so the sentence no longer points at the rounded surface figure, then added the byte-exact clause scoped strictly to registration (no claim of quota checks at proxy completion or elsewhere, matching impl).

2. *Edit 2 (bid-submit state gate)*
   - (a) Subject: whether bid submission is state-gated on the turnover and the error classification per turnover state.
   - (b) Paths enumerated: `vendor_bids.py::create_bid` (lines 49-112 — the exact mapping inserted); `vendor_bids.py::award_bid` (lines 148-161 — own STAGED gate, already pinned by §3.5, untouched by the new sentence); `vendor_bids.py::withdraw_bid` (lines 208-226 — no turnover-state gate, wording scoped to submission only); `turnovers.py::void_turnover` (lines 305-328 — SUBMITTED→EXPIRED cascade stays in code; vacuous-but-true under the gate since a DRAFT turnover can hold no bids, mechanism stays reachable via vendor suspension in `routes/vendors.py:127`, so the existing §3.5 cascade sentences were kept verbatim); `services/transitions.py::guard_transition` (embodies the §2.9 from-state/terminal rule the new sentence defers to); PRD §4 table row ("Submit a bid against a `STAGED` turnover") — consistent.
   - (c) Adjustment: worded as an acceptance condition with explicit per-state error mapping (rather than calling bid creation a "transition" on the turnover), since `create_bid` is a create endpoint that nonetheless applies §2.9's terminal-state reporting rule.

## Step 9: Complete PRD — 2026-08-15T00:20:00.000Z

All edits verified. The diff touches 38 paragraph lines, all in-place (399 → 399 lines; +6,551 chars). Work is complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (399 lines, 69,636 chars) → `PRD_COMPLETED.md` (399 lines, 76,187 chars; +6,551 chars, 38 paragraph lines revised in place; no sections added or removed).

**Counts:** 47 ambiguity-pins, 5 mismatch-revisions (52 distinct behavior pins across 22 edited paragraphs).

**Changes** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.1 — insert — ambiguity — empty `X-User-ID`/`X-User-Role` value counts as missing — middleware.py:28
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the facility logical clock (point 5) — response.py:17-18
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` = `offset+limit < total_count` — helpers.py:216-249, response.py:41
- §2.3 — insert — ambiguity — `created_at` sort ties broken by `id` ascending (pervasive under a frozen logical clock) — helpers.py:254
- §2.4 — insert — ambiguity — no-show sweep boundary: past date, or same date once current logical hour ≥ `end_hour` — routes/clock_routes.py:15-29
- §2.5 — insert — ambiguity — `created_at`/`updated_at` read the logical clock; `version` starts at 1 — helpers.py:20-39
- §2.6 — insert — ambiguity — FK naming an entity of another project does not resolve → `ERR_NOT_FOUND` — routes/assets.py:72-74 (pattern in all routes)
- §2.9 step 4 — insert — ambiguity — named-uniqueness violations (batch_label, profile_name, bay_name, vendor_name, per-kind sequence_label, round_label) → `ERR_INVALID_REQUEST` — routes/batches.py:68-78, watermark_profiles.py:97-106, bays.py:75-81, vendors.py:80-86, turnovers.py:60-72, review_rounds.py:74-83
- §2.9 step 4 — insert — mismatch — pipeline-order exception: change-list `entries` shape validated before entry `asset_id` resolution; QC-report `verdict`/`fail_codes` before optional `asset_id` resolution — routes/change_lists.py:117-126, deliverables.py:224-280
- §2.9 step 20 — revise — ambiguity — activation preconditions also fail with `ERR_PROJECT_NOT_WRAPPABLE` — routes/projects.py:150-156
- §3.1 — insert — ambiguity — activation without AVAILABLE bay + ACTIVE profile → `ERR_PROJECT_NOT_WRAPPABLE` (422) — routes/projects.py:150-156
- §3.1 — revise — mismatch — `conform_ready` recompute triggers aligned to impl: asset registered/conformed/locked, change list applied/rejected, CUT-or-DELIVERABLE round approved, turnover issued (no recompute on round rejection) — routes/assets.py:135,254,283; change_lists.py:251,268; review_rounds.py:170-171; turnovers.py:196-198
- §3.2 — insert — ambiguity — asset registration performs no batch-lifecycle-state check — routes/assets.py:60-74
- §3.2 — insert — ambiguity — finish-ingest with zero assets or nonzero failed count → `ERR_INVALID_STATE` — routes/batches.py:157-163
- §3.2 — insert — ambiguity — proxy-complete takes non-negative integer `proxy_bytes`, no asset lifecycle-state check — routes/assets.py:170-179
- §3.2 — insert — ambiguity — READY-batch purge guard violations → `ERR_INVALID_STATE` — routes/batches.py:195-218
- §3.2 — insert — ambiguity — batch list filterable by `status` — routes/batches.py:101-103
- §3.2 — insert — ambiguity — verify while proxy incomplete → `ERR_INVALID_STATE` — routes/assets.py:207-211
- §3.3 — insert — ambiguity — LOCKDOWN activation refusal → `ERR_INVALID_STATE` (409) (point 4) — routes/watermark_profiles.py:145-152
- §3.3 — insert — ambiguity — retirement refusal while PUBLISHED package references profile → `ERR_INVALID_STATE` — routes/watermark_profiles.py:168-178
- §3.3 — insert — ambiguity — `distribution_list` validated eagerly at creation as body shape (`ERR_INVALID_REQUEST`) — routes/dailies.py:79-109
- §3.3 — insert — ambiguity — publish on non-ACTIVE project → `ERR_INVALID_STATE`, evaluated with the from-state check before watermark compliance — routes/dailies.py:160-168
- §3.4 — insert — ambiguity — booking creation does not gate on bay status; maintenance/decommission reach bookers only via the OCC version advance — routes/bookings.py:52-149
- §3.4 — revise — mismatch — utilization read returns a single `object` for one date; omitted `session_date` defaults to the current logical date; dropped the per-day-rollup ordering clause (never exhibited) (point 7) — routes/bays.py:202-214
- §3.5 — insert — ambiguity — offboard with in-flight turnovers → `ERR_INVALID_STATE` — routes/vendors.py:149-161
- §3.5 — insert — ambiguity — stage precondition failures (non-ACTIVE project; CONFORM without VERIFIED/CONFORMED asset) → `ERR_INVALID_STATE` — routes/turnovers.py:126-144
- §3.5 — revise — ambiguity — conform precondition pinned as a project-level existence check (turnovers carry no per-asset references); failure → `ERR_INVALID_STATE` (point 1) — routes/assets.py:227-251
- §3.5 — insert — ambiguity — lock with a referencing OPEN change list → `ERR_INVALID_STATE` — routes/assets.py:267-280
- §3.5 — insert — ambiguity — bid `vendor_id` ≠ `X-User-ID` at submit → `ERR_INVALID_REQUEST` (400) (point 3) — routes/vendor_bids.py:70-77
- §3.5 — insert — ambiguity — award: non-STAGED parent → `ERR_INVALID_STATE`/`ERR_ALREADY_TERMINAL`; double award → `ERR_INVALID_STATE` — routes/vendor_bids.py:148-173
- §3.5 — insert — ambiguity — withdraw of another vendor's bid → `ERR_INVALID_STATE` (point 3) — routes/vendor_bids.py:217-223
- §3.5 — insert — ambiguity — issue: no AWARDED bid or vendor_id mismatch → `ERR_INVALID_STATE` — routes/turnovers.py:159-177
- §3.5 — insert — ambiguity — ack ownership mismatch → `ERR_INVALID_STATE` (point 3) — routes/turnovers.py:213-219
- §3.5 — insert — ambiguity — return ownership mismatch / OPEN change list → `ERR_INVALID_STATE`; auto-created round's `round_label` = `VENDOR_RETURN-` + `sequence_label` (point 3) — routes/turnovers.py:234-264
- §3.5 — insert — ambiguity — close before the auto-round reaches APPROVED/VOID → `ERR_INVALID_STATE` — routes/turnovers.py:276-293
- §3.5 — revise — mismatch — vendor load: single ISSUED+ACKED count backs both the computed read and the issue-time capacity check; no capacity evaluation at award; recomputation never mutates the vendor record (no version bump) — routes/vendors.py:46-52,172-185; turnovers.py:185-191
- §3.5 — insert — ambiguity — change-list creation: no turnover-status gate, empty `entries` accepted, `frames_delta` any integer — routes/change_lists.py:100-145
- §3.5 — revise — mismatch — TRIM reduces `duration_frames` clamped at zero; DELETE sets `duration_frames` to zero outright; ADD/SLIP leave it unchanged (point 6) — routes/change_lists.py:228-239
- §3.5 — insert — ambiguity — turnover list filters (`status`, `turnover_kind`, `vendor_id`) and bid list filters (`turnover_id`, `vendor_id`, `status`) — routes/turnovers.py:94-102, vendor_bids.py:121-129
- §3.6 — insert — ambiguity — `target_ref_id` resolves against the entity class implied by `target_kind` (DAILIES→package, DELIVERABLE→deliverable, CUT/VENDOR_RETURN→turnover) — routes/review_rounds.py:48-62
- §3.6 — insert — ambiguity — note creation not gated on round status — routes/review_notes.py:47-80
- §3.6 — insert — ambiguity — note ack/resolve under a wrong round status → `ERR_INVALID_STATE` — routes/review_notes.py:116-122,142-149
- §3.6 — insert — ambiguity — round approval-gate violation → `ERR_INVALID_STATE` — routes/review_rounds.py:158-167
- §3.6 — insert — ambiguity — round-reject cascade leaves an already REJECTED/DELIVERED/SUPERSEDED deliverable untouched — routes/review_rounds.py:188-199
- §3.7 — insert — ambiguity — render against false `conform_ready` → `ERR_INVALID_STATE` — routes/deliverables.py:155-162
- §3.7 — insert — ambiguity — enqueue-qc with `requires_qc` false → `ERR_INVALID_STATE` — routes/deliverables.py:201-208
- §3.7 — revise — ambiguity — `fail_codes` required **and non-empty** on FAIL — routes/deliverables.py:229-242
- §3.7 — insert — ambiguity — deliver: non-ACTIVE project on QC_PASSED path → `ERR_INVALID_STATE`; RENDERED with `requires_qc` true → `ERR_INVALID_STATE` — routes/deliverables.py:340-368
- §3.7 — insert — ambiguity — rejection cascade targets the DELIVERABLE-kind round still OPEN/NOTES_CLOSED; terminal rounds untouched — routes/deliverables.py:394-403
- §3.8 — insert — ambiguity — `bytes_written` zero from creation; in-scope asset set is all non-PURGED project assets for every scope; SOURCES_ONLY sums `source_bytes` only, SOURCES_AND_PROXIES/FULL_PROJECT sum source+proxy (point 2) — routes/archive_jobs.py:61-72,84-96,153-161
- §3.8 — insert — ambiguity — archive start with another job WRITING/VERIFYING → `ERR_INVALID_STATE` — routes/archive_jobs.py:130-143
- §3.8 — insert — ambiguity — FULL_PROJECT seal outside WRAPPING/CLOSED → `ERR_INVALID_STATE` — routes/archive_jobs.py:172-183

All seven flagged interpretation points were verified against the code and pinned. Consciously left unpinned as non-divergent or non-API surface: 405/unhandled-exception handlers, the absence of API triggers for FAILED transitions (checksum/proxy-crash/tape-error events), and ISO-parser leniency details.
