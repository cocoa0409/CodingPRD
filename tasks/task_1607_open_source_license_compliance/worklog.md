## Step 2: Generate Scaffold — 2026-08-14T02:05:00.000Z

All three files are written and the lint is clean. Here's the summary.

## Scaffold Generation Complete

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1607_open_source_license_compliance/SCAFFOLD.yaml` (§1.0–§1.7)
- `/home/ubuntu/github/CodingPRD/tasks/task_1607_open_source_license_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1607_open_source_license_compliance/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key `scaffold_corner_design`)

**Coverage audit:**
- **Entities**: 12 (Product, Component, DependencyScan, BillOfMaterials, BomEntry, LicenseApprovalRequest, ObligationTicket, Vulnerability, VulnerabilityFinding, ReleaseGate, RemediationPlan, AuditEngagement)
- **Endpoints**: 84 (CRUD + action + filtered-list + test-driving `/_clock/set_current_utc`, `/_vulnerability-feed/simulate`, `/_scan-worker/process-next`)
- **State machines**: 9 (Product posture-driven, DependencyScan linear, BillOfMaterials lifecycle, LicenseApprovalRequest approval chain, ObligationTicket, VulnerabilityFinding branching, ReleaseGate evaluation, RemediationPlan, AuditEngagement)
- **Calculations**: 7 (license classification, obligation determination, BOM posture, release gate evaluation, remediation SLA, scan coverage, audit findings)
- **Validations**: 10 priorities (auth → existence → state → safety → referential → temporal → fiscal)
- **Errors**: 54 codes
- **Roles**: 8 (ComplianceAnalyst, LegalCounsel, EngineeringManager, SecurityAnalyst, ReleaseManager, CISO, PlatformAdmin, Any)
- **Concurrency rules**: 2 (OCC on Product.version for scan creation, OCC on BillOfMaterials.version for gate evaluation)

**§1.8 Difficulty Design**: 18 instances (2 per rule × 9 rules)
- `dual_variant_calc`: AGPL obligation differs SaaS vs ON_PREMISE; release gate strict mode EMBEDDED vs SaaS
- `combinatorial_formula`: 3-input non-linear obligation formula; circular SLA deadline dependency
- `non_linear_state_machine`: LicenseApprovalRequest cyclic withdraw/resubmit; VulnerabilityFinding branching mitigate vs direct
- `transitive_cascade`: Scan→BOM→Product depth-3; Component→BomEntry→BOM depth-2
- `priority_pair_validation_conflict`: state vs business_safety; business_referential vs business_temporal
- `boundary_precision_check`: warning count 3 vs 4; obligations fulfilled 100.00% vs 99.00%
- `cross_entity_state_dependency`: ReleaseGate→BOM+Product; RemediationPlan→Component
- `resource_temporal_overlap`: approval expiry point-in-time; audit vs remediation window overlap
- `compensating_invariant`: Product.version monotonicity; vulnerability count balance

**§1.9 Corner Design**: 34 instances across 9 sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross_cutting, consistency_model), with 5 `excluded_because` stubs for corners already covered by §1.8.

**Lint verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Step 3: Copy Shared Files — 2026-08-14T02:05:30.000Z

Copied ./INSTRUCTION.md → tasks/task_1607_open_source_license_compliance/workspace/INSTRUCTION.md (bash-only step).

## Step 4: Generate PRD — 2026-08-14T02:30:00.000Z

All contracts pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1607_open_source_license_compliance/workspace/PRD.md` — 356 lines.

**Sections written:**
- **§1 Introduction** (2 paragraphs: business context + system scope)
- **§2 Global Specifications** (10 subsections): 2.1 RBAC (all 7 roles named with opaque-identity prose + `Any` read role), 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending), 2.4 Resource Identity (UUID `id`, 3-fractional-digit timestamps, `version`), 2.5 Request Evaluation Order (all 10 validation layers in priority order), 2.6 Hierarchical Resolution & Cross-Reference Retrieval (left-to-right 404s + all filtered-list query params), 2.7 Classification & Posture vocabulary, 2.8 OCC (both rules), 2.9 Logical Time (default 2026-08-01T00:00:00Z), 2.10 Precision/Hashes
- **§3 Business Logic** (8 subsections): product posture lifecycle, component catalogue & the 18-identifier license classifier, scan pipeline & BOM assembly, obligation determination & two-stage approval, vulnerability intake & SLA triage, remediation planning, release gating, audit engagements & clock sweeps
- **§4 Endpoint Definitions**: 84 rows, 4 columns (Method / Path / Description / Authorized Role)
- **§5 Error Code Catalogue**: 54 rows, 2 columns (Error ID / HTTP Status)

**Self-audit results:**

```
Field coverage check:
- entities[].fields: 100 required, 100 present, 0 missing
- endpoints[].request_body: 46 required, 46 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in prose (§2.5 ordered layers), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (scan-create → expected_product_version; gate-evaluate → expected_bom_version; both → ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 58 checked, 58 fully expressed (from/to/precondition/side-effects), 0 missing
- calculations[]: 7 checked, 7 fully expressed (classification catalogue, obligation matrix, bom_posture, gate ladder, SLA deadlines, coverage %, audit critical count), 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 84 checked, 84 expressed, 0 missing
- entities[].fields[] structured content: 100 checked, 100 reconstructible (defaults, null-until-scan, 90-day expiry, SLA constants), 0 missing
- sibling-branch symmetry: 9 groups checked (STRONG_COPYLEFT branches, WEAK_COPYLEFT branches, verdict ladder, SLA severities, cancel/withdraw/waive/wont-fix/verify/abandon/audit-cancel sibling transitions, scan FAILED siblings), 9 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 517
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0 (the single `PATCH` token is the plan_type enum value — required verbatim by enum fidelity — not an endpoint-identifier position; reviewed false positive)
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 54 error IDs appear in §2/§3 narrative as well as §5; all 43 state values backticked; no fuzzy/approximating words; no operator-syntax leaks (`==`, `>=`, `IN {}` etc.); no invented rules. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened or referenced.

## Step 6: Generate Implementation — 2026-08-14T02:50:00.000Z

The implementation is complete and verified. Summary:

**Files written** (all under `workspace/implementation/`):

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"` (no-op on per-test reboots), then `exec python3 app.py` in the foreground
- `requirements.txt` — flask only
- `app.py` — Flask entry point, blueprint registration, error handlers (ApiError → envelope, 404 → `ERR_RESOURCE_NOT_FOUND`, 400 → `ERR_INVALID_REQUEST`), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` (12 entity dicts, all empty at boot), logical clock (default `2026-08-01T00:00:00Z`), UUID/id/ISO-8601-ms helpers, `touch()` revision bumper
- `errors.py` — full error catalog (50 error IDs with exact HTTP statuses from the scaffold)
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta`, defaults 10/0, clamp 1–100)
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (7 roles), role gating, JSON body parsing
- `services/policy.py` — license classification catalogue (18 SPDX ids, conservative RESTRICTED default, AGPL-3.0+SaaS → PROHIBITED, SSPL-1.0+SaaS → PROHIBITED), obligation determination (fixed order: PROHIBITED → scope TEST/DEV → PERMISSIVE/WEAK/STRONG/RESTRICTED with distribution-model variants), BOM posture thresholds (incl. EMBEDDED strict mode), round-half-up-2dp helper
- `services/engine.py` — cross-aggregate recomputation (BOM tallies, product counts, entry vuln max), posture state machine with cascades (BLOCKED fails open gates, expires PENDING approvals, overdues past-due tickets), BOM finalization cascade (supersede older FINALIZED BOMs, spawn approval requests for unapproved RESTRICTED entries, spawn obligation tickets), synchronous scan pipeline, time sweep (ticket overdue, approval expiry 30d/expiry_at, gate expiry 14d/evaluation_expires_at, deadline flagging), vulnerability propagation, remediation SLA computation (7/30/90/180d, license-change 14d cap, BLOCKED 3d cap)
- `routes/` — 12 modules: products, components, scans, boms, approvals, tickets, vulnerabilities (vulnerabilities + findings), gates, plans, engagements, admin (clock/feed/scan-worker), standalone (11 flat single-resource GETs + 9 filtered list GETs)

**Endpoint count: 84** (73 scaffold-declared + the verb routes it enumerates; all paths from the scaffold endpoint table are implemented, including the standalone `/oss-products/<entity>/{id}` aliases and flat filtered lists).

**Design decisions worth recording:**

1. **Component `version` collision** — PRD §2.4's naming note: a Component's client-supplied `version` is the package version string, distinct from the system revision counter. Components keep `version` as the package string in the JSON view and carry the revision counter internally as `_rev` (never serialized; `touch()` detects non-int `version` and bumps `_rev`). Components have no OCC rules, so no external behavior depends on it.
2. **Unscanned-component classification fallback** — a freshly registered Component has no computed classification; `effective_classification` falls back to classifying `declared_license_spdx` so remediation-plan license-compatibility checks have a conservative value (matches PRD's "never fails open" intent).
3. **BLOCKED de-escalation is manual-only** — `reevaluate_product_posture` never auto-exits BLOCKED; only the CISO unblock endpoint moves BLOCKED → AT_RISK, and it verifies every PROHIBITED entry has an IN_PROGRESS/COMPLETED remediation plan.
4. **Manifest ingestion** — scan creation accepts a `manifest_components` (or `components`) array in the request body; `raw_manifest_hash` is the SHA-256 of its canonical JSON. Declared licenses classifying PROHIBITED are rejected at submission with `ERR_PROHIBITED_COMPONENT` (403); prohibitions that only surface via discovered license (e.g. AGPL in a SaaS product) block the product at scan completion, per the PRD's layered model.
5. **Approval-request withdrawal ownership** — auto-spawned requests (from scan completion) record `requested_by: None`, treated as withdrawable by any ComplianceAnalyst; requests with a recorded requester enforce the original-requester rule.
6. **Ticket due dates** — set to creation-time + 30 days (the PRD's "release date minus a buffer" has no concrete release date input, so a fixed buffer is used; the clock sweep drives OVERDUE transitions deterministically).

Verified via live smoke tests: auth/permission/existence ordering, OCC 412s on both rules, full scan→BOM→notice→gate→ticket→vuln→remediation→audit pipeline, AGPL-SaaS blocking, EMBEDDED strict YELLOW, archive preconditions, time sweep, and fresh-boot empty state (total_count 0, default clock). All modules compile; `bash start.sh` boots and serves within ~2s.

## Step 5: Generate Unit Tests — 2026-08-14T03:50:00.000Z

All checks complete. Here is the summary.

### Files written

**`test_helpers/`** (9 files, ~1900 lines) under `test_helpers/`:
- `types.py` — 12 entity TypedDicts + 20 status/vocabulary enums. Component's `version` is typed as the package-version string per the PRD §2.4 naming note (no system `version` on Component).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint row (~70 methods: product/component/scan/BOM/entry/approval/ticket/vulnerability/finding/gate/plan/engagement hierarchies, the 3 admin test-driving endpoints, 11 standalone detail GETs, 9 flat filtered listings).
- `api_errors.py` — all 56 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` + `assert_percentage_two_decimals` (PRD §2.10 round-half-up).
- `factories.py` — payload factories incl. `manifest_component_spec` (one manifest line of a scan submission) and OCC-aware `create_dependency_scan_payload`.
- `constants.py` — SLA table (7/30/90/180d), 14-day license-change cap, 3-day BLOCKED cap, 90-day approval validity, 30/7-day gate expiries, warning ceiling 3, 80% coverage floor, startup clock.
- `test_users.py` — 7 opaque role headers + per-instance `make_*_headers` builders (analyst ids threaded for the withdrawal requester comparison).
- `fixtures.py` — composite fixtures: `setup_product_with_completed_scan`, `setup_blocked_product` (declared-MIT/discovered-WTFPL manifest line), `setup_product_with_finding`, `setup_product_with_approval_request`, `setup_gate_ready`, `verify_finding_via_remediation` (plan→approve→start→complete→verify chain), `fulfill_all_obligation_tickets(leave_unresolved=N)`, OCC-safe `create_scan`/`evaluate_gate` (fresh version re-read), `approve_license_request`, clock/vuln helpers.
- `__init__.py` — barrel (framework generics + PRD-specific).

**`test_suite/`** (9 files, ~1900 lines): `conftest.py` (session `api` + 7 role fixtures) and `test_01`…`test_08` organized by concern (products/catalogue, scan-BOM pipeline, obligations/classification, approval workflow, vulnerability findings, release gates, remediation/audit, security/OCC).

### Test counts per design-index queue
- **Queue A (Difficulty): 18/18 instances, exactly 2 tests each = 36 tests** — coverage target met.
- **Queue B (Corner): 28/29 non-stub instances, 1 test each = 28 tests**. 5 `excluded_because:` stubs not translated; all 5 cross-references verified to resolve. Total 64 tests.

### Instances skipped (1)
- `Corner/endpoints/generate_notice_conditional_action` — asserts `ERR_BOM_NOT_FINALIZED` when generating a NOTICE file on a DRAFT BOM. PRD names no state precondition for generate-notice (the error id is tied only to gate creation in §3.7), and a DRAFT BOM is unreachable via PRD-declared endpoints (the scan worker drives synchronously to COMPLETED; the BOM is created mid-pipeline). Fails both coverage and reachability — gap left as a gap.

### Notable PRD-first adjudications (translated with corrected fixtures, documented in docstrings)
- `obligation_determination_saas_vs_onpremise_agpl`: the literal SaaS+AGPL pair is PRD-self-contradictory (§3.2 upgrades SaaS+AGPL to PROHIBITED → §3.4 rule 1 yields PROHIBITED_USE, conflicting with §3.4's AGPL→FULL_SOURCE_DISCLOSURE sentence). Instance covered with two uncontested distribution pairs (LGPL-2.1 SaaS vs ON_PREMISE; GPL-3.0 MOBILE_APP vs ON_PREMISE).
- `remediation_sla_circular_dependency`: recipe never establishes BLOCKED; fixture blocks the product via a discovered-WTFPL scan, preserving the asserted deadline (2026-08-06) and the min(severity, now+3d) semantics; plus an unblocked control test.
- `vulnerability_finding_branching_mitigate_vs_direct`: recipe omitted the required `remediation_status == VERIFIED` precondition; the plan-completion subflow was added.
- `vulnerability_count_balance_through_lifecycle`: recipe marks a CONFIRMED finding false-positive (PRD allows FP only from OPEN); the FP is applied to the unconfirmed finding.
- `release_gate_depends_on_bom_and_product`: DRAFT-BOM gate unreachable (creation itself requires FINALIZED); tested via SUPERSEDED-BOM creation refusal (`ERR_BOM_NOT_FINALIZED`) + BLOCKED-product refusal.
- `error_prohibited_component_triggerable` and the warning/strict/pct gate instances: recipes never attached content to scans; fixtures submit `manifest_components` (the reading of §3.3's "referenced manifest" under which the prohibited-content screen and all scan cascades are exercisable).
- `scheduled_deferred_action_expiry`: yaml assert was self-contradictory (claims approval EXPIRED while noting its 90-day expiry unreached); test asserts the PRD-derivable outcomes (gate EXPIRED past its 30-day evaluation expiry, approval still APPROVED).
- `ciso_can_bypass_gate`: recipe's WTFPL setup BLOCKs the product (which forbids bypass); rebuilt with a warning-only gate.

### Self-check results
- **Stage 1**: all 9 helper modules import cleanly (`import test_helpers` OK); pyflakes clean.
- **Stage 2 completeness audit (scripted)**: 64/64 tests carry exactly one terminal `Design:` tag; every tag resolves to a real instance; none point at stubs; difficulty ≥2 everywhere; corner ≥1 on 28/29 (single documented skip); 5 stub pointers resolve.
- **PRD-citation pass (scripted)**: 64/64 docstrings contain a rule-bearing quote whose ≥8-word window survives literal grep of PRD.md; every asserted error id appears in PRD prose (not only §5); the two priority tests quote §2.5's ordered-pipeline sentence; no `skip`/`skipif`/`xfail` anywhere.
- **Live verification** (`prd-bench-local-run --isolation per-test-server` against the pre-existing `workspace/implementation`): **60/64 pass**. One failure (`test_exactly_100_percent_passes`) was a transient dev-server connection reset and **passes standalone**. The 3 remaining failures are contract-defining PRD-vs-implementation gaps for the bench iteration to fix: (1) impl eagerly derives a fresh component's `effective_classification` from the declared license, violating §3.2's "no policy classification computed yet"; (2) impl never raises `ERR_APPROVAL_EXPIRED` at gate evaluation despite §2.5 layer 9; (3) impl resolves EVALUATING→PASSED/FAILED synchronously inside evaluate, making the §3.7 CISO bypass of an EVALUATING gate unreachable.

## Bench iteration: diagnose + fix to a clean 8-round sweep — 2026-08-14T04:10:00.000Z

Baseline sweep (8 parallel rounds): 61/64 in every round; union of failures = three deterministic tests plus one transient (test_stale_product_version_rejected hit ConnectionResetError in rounds 5/6 under 8-way load; server logs clean, infrastructure-level keep-alive race).

Diagnosis (all three deterministic failures kept after STEP 1 coverage + unique-derivability and STEP 2 test-fidelity checks; all traced to verbatim PRD sentences):
1. test_component_computed_fields_ignore_input — PRD §3.2 "no policy classification computed yet"; impl's effective_classification() fell back to classifying the declared license. Fix in services/policy.py: effective is now override ?? license_policy_classification, else None.
2. test_evaluation_past_approval_expiry_rejected — PRD §2.5 layer 9 + §3.4 "an approval invoked past its expiry_at is no defense at ... gate evaluation, surfacing ERR_APPROVAL_EXPIRED"; impl only filtered expired approvals from the warning tally. Fix in routes/gates.py evaluate_gate: layer-9 check raises ERR_APPROVAL_EXPIRED when a RESTRICTED entry's approval has expiry_at in the past (fires whether or not the sweep already flipped status to EXPIRED).
3. test_ciso_can_bypass_gate — PRD §3.7 bypass is defined only for an EVALUATING gate; impl resolved EVALUATING→PASSED/FAILED synchronously inside evaluate, making bypass unreachable. Fix: evaluate leaves the gate EVALUATING with the verdict recorded (evaluation_result, counts, 30-day expiry for passing verdicts); the time sweep (services/engine.py time_sweep) completes EVALUATING→PASSED/FAILED per the recorded verdict, then applies the PASSED/BYPASSED expiry rule — preserving §3.7's ladder sentence and the §2.9/§3.7 expiry sentences.
4. Infra hardening: app.py now runs Werkzeug with threaded=True (no PRD-observable change) to absorb the keep-alive reset race seen under 8-way parallel load.

Post-fix sweep: 8/8 rounds × 64/64 passed. No tests deleted; no test_helpers/test_suite changes needed.

## Step 7: Run Tests and Iterate — 2026-08-14T04:20:00.000Z

Clean 8-round sweep achieved: **8/8 rounds × 64/64 tests passed**.

**Iterations run:** 2 sweeps (baseline diagnosis sweep → fix → verification sweep). Baseline: 61/64 in all 8 rounds; union of failures = 3 deterministic tests + 1 transient. Post-fix: 64/64 in all 8 rounds, zero flakes.

**Tests deleted:** none. All three failing tests survived STEP 1 (PRD verbatim coverage + unique derivability) and STEP 2 (test-vs-PRD fidelity); all were implementation bugs.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`** (all under `workspace/implementation/`):

1. `services/policy.py` — `effective_classification()`: removed the eager fallback that classified a fresh component's *declared* license. PRD §3.2 ("no policy classification computed yet" for a freshly registered component; effective = override when set, else the computed `license_policy_classification`). Fresh components now report `license_policy_classification`/`effective_classification` as null. Fixed `test_component_computed_fields_ignore_input` (8/8 rounds).

2. `routes/gates.py` — `evaluate_gate()`: added the §2.5 layer-9 / §3.4 check — after the notice-file check, any RESTRICTED BOM entry whose approval request has `expiry_at` in the past raises `ERR_APPROVAL_EXPIRED` (409). Since `expiry_at` is only ever set by an approval decision, the check fires exactly for granted-then-lapsed approvals, whether or not the clock sweep has already flipped their status to EXPIRED. Fixed `test_evaluation_past_approval_expiry_rejected` (8/8 rounds).

3. `routes/gates.py` `evaluate_gate()` + `services/engine.py` `time_sweep()`: evaluate now leaves the gate in `EVALUATING` with the verdict recorded (`evaluation_result`, counts, 30-day `evaluation_expires_at` for passing verdicts); the time sweep completes `EVALUATING`→`PASSED`/`FAILED` per the recorded verdict and then applies the `PASSED`/`BYPASSED` expiry rule. The synchronous-resolution reading had made §3.7's CISO bypass (defined only for an `EVALUATING` gate, with detailed side effects and error) unreachable dead code; the fix preserves the ladder sentence ("moves the gate from `EVALUATING` to `FAILED`/`PASSED`") while leaving the bypass pathway exercisable. Fixed `test_ciso_can_bypass_gate` (8/8 rounds) while keeping `test_clock_sweep_expires_gate_but_not_unexpired_approval` green (EVALUATING+PASS resolves to PASSED then expires in the same sweep → EXPIRED).

4. `app.py`: `app.run(..., threaded=True)` — pure runtime hardening, no PRD-observable change. Absorbs the keep-alive connection-reset race that hit `test_stale_product_version_rejected` in rounds 5/6 of the baseline sweep under 8-way parallel load (server logs showed no crash; ~140 sibling task implementations use the same setting). Did not recur in the verification sweep.

All fixes were smoke-tested against a live server before the verification sweep (fresh-component null classification, `ERR_APPROVAL_EXPIRED` at evaluation, bypass of an EVALUATING gate with 7-day expiry, and sweep-driven EVALUATING→PASSED→EXPIRED resolution).

## Step 8: Finalize PRD — 2026-08-14T04:35:00.000Z

The diff is exactly 7 revised lines, no other drift. Final verification: line counts are equal (355/355), all edits are inline revisions within existing sections, no new sections added, fix 4 (`app.py threaded=True`) required no PRD edit as step_7_diff explicitly marks it PRD-unobservable.

**File produced:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 355 lines; PRD_FINALIZED.md = 355 lines (0.0% delta — all edits are inline revisions of existing sentences; character delta is confined to 7 lines).

**Changes (one bullet per edit):**
- §3.2 — revise — pinned that a freshly registered component reports `license_policy_classification` and `effective_classification` as null (registration never classifies the declared license; classification is computed only when a scan completes) — `implementation/services/policy.py:49-62`, `implementation/routes/components.py:38-52`
- §2.5 layer 9 — revise — pinned the gate-evaluation `ERR_APPROVAL_EXPIRED` check as a direct `expiry_at`-vs-logical-clock comparison that fires for granted-then-lapsed approvals regardless of sweep status, and corrected the BOM-finalization claim (no error there; a lapsed approval counts as no approval) — `implementation/routes/gates.py:130-147`, `implementation/services/engine.py:66-79,306-332`
- §3.4 — revise — same fix-2 alignment in the approval-workflow narrative tail (error surfaces at gate evaluation; at finalization the lapsed approval simply does not count) — same impl sites
- §3.7 evaluation paragraph — revise — pinned that evaluation records the verdict and leaves the gate in `EVALUATING` (counts/verdict visible, CISO-bypassable), with the system completing `EVALUATING`→`FAILED`/`PASSED` in the clock sweep, including same-sweep expiry of a freshly `PASSED` gate; defined `OPEN`∪`EVALUATING` as "open gate" for the §3.1/§3.3 cascades — `implementation/routes/gates.py:183-219`, `implementation/services/engine.py:537-549`
- §3.7 expiry paragraph — revise — supersede expiry also covers `EVALUATING` gates; the fourteen-day expiry stays `OPEN`-only — `implementation/services/engine.py:288-292,531-536`
- §2.9 — revise — sweep description now includes completing `EVALUATING` gates per recorded verdict, with same-sweep `PASSED`→`EXPIRED` — `implementation/services/engine.py:537-549`
- §3.8 — revise — same EVALUATING-completion clause in the parallel sweep description — `implementation/services/engine.py:537-549`

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**

- **Edit 1 (§3.2, null classification).** (a) Subject: component classification fields at registration / `effective_classification` semantics. (b) Enumerated: `policy.py:49-62`; `components.py:15-18,38-52,63-65`; `engine.py:82-86,404,460-475`; `boms.py:26,77-80`; `standalone.py:186-189`; `plans.py:39-41`; `engagements.py:152-158`. (c) Scoped the wording to "freshly registered / until a scan completes" so it does not collide with the adjacent §3.2 fallback sentence (a *computed* classification of a null/unrecognized discovered license is `RESTRICTED` — `policy.py:22-38`), which describes scan-time classification, not registration-time reporting.

- **Edits 2-3 (§2.5 layer 9 + §3.4, approval expiry).** (a) Subject: where/how approval expiry is enforced. (b) Enumerated: `gates.py:130-147` (only `ERR_APPROVAL_EXPIRED` raise site); `approvals.py:107-111` (`expiry_at` set only on engineering APPROVE, +90 days); `engine.py:66-79` (`approved_component_ids` filters expired), `engine.py:306-332`, `engine.py:510-523`, `engagements.py:161-172`. Confirmed finalization never raises. (c) Removed the original sentence's claim that the 409 is "enforced … at BOM finalization"; replaced with "counts as no approval at all". Kept the gate check scoped to "approval request covering the component of a `RESTRICTED` entry in the BOM under evaluation".

- **Edits 4-7 (§3.7 ×2, §2.9, §3.8, EVALUATING lifecycle).** (a) Subject: gate state machine around `EVALUATING`. (b) Enumerated every `EVALUATING` reference: `gates.py:183-218`, `gates.py:222-238`, `engine.py:190-196`, `engine.py:264-272`, `engine.py:288-292`, `engine.py:530-554`, `boms.py:127-130`. Verified no path other than the sweep completes EVALUATING→PASSED/FAILED, and that only a BOM supersede expires an EVALUATING gate. (c) Added the explicit "open gate = OPEN or EVALUATING" definitional sentence enumerating the exact cascade sites; explicitly carved the fourteen-day expiry out as OPEN-only; widened the supersede-expiry sentence to include EVALUATING; worded the sweep clause to cover the same-sweep `PASSED`→`EXPIRED` resolution.

**Fix 4 (`app.py` `threaded=True`):** no PRD edit — step_7_diff explicitly marks it as runtime hardening with no PRD-observable change.

## Step 9: Complete PRD — 2026-08-14T04:45:00.000Z

All verification checks pass — no leftover unrevised phrases, and `ERR_LICENSE_SCAN_INCOMPLETE` now appears only in the error catalogue (matching `errors.py`, which defines but never raises it) with the §3.3 narrative explicitly stating it is not raised. The work is complete.

**File produced:** `workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (355 lines / 57,379 chars) → `PRD_COMPLETED.md` (355 lines / 62,242 chars); char-delta **+4,863**. All edits are in-paragraph inserts/revisions; no sections added, 31 paragraphs touched.

**Counts:** 25 ambiguity-pins, 19 mismatch-revisions (implementation was the authority throughout; all 64 tests pass against impl per `results.*.json`).

**Mismatch revisions** (PRD described behavior impl does not exhibit):
- §2.5 layer 6 — revise — removed "absent a CISO waiver" (no waiver mechanism exists) — `routes/scans.py:60-66`
- §2.5 layer 8 — revise — nonexistent plan target draws `ERR_COMPONENT_NOT_FOUND` (404); `ERR_INCOMPATIBLE_LICENSE` only for existing incompatible targets — `routes/plans.py:76-84`
- §2.8 — revise ×2 — `expected_product_version` / `expected_bom_version` are optional (omitted = no check; non-integer = `ERR_INVALID_REQUEST`), not required — `routes/scans.py:47-54`, `routes/gates.py:111-119`
- §3.1 — revise — AT_RISK triggers on unapproved RESTRICTED in the active BOM immediately (no seven-day wait) — `services/engine.py:230-240`
- §3.1 — revise — BLOCKED only from PROHIBITED in active BOM; the "CRITICAL open >7 days → BLOCKED" rule is not implemented (also removed from §3.5) — `services/engine.py:227-229`
- §3.1 & §3.7 — revise ×2 — AT_RISK slide only increments gates' `warning_findings_count`; `evaluation_result` is never recomputed — `services/engine.py:259-272`
- §3.1 — revise — BLOCKED cascade flips OPEN **or IN_PROGRESS** past-due tickets, and unblock pins: `justification` accepted without validation, coverage = IN_PROGRESS/COMPLETED plan targeting the component or its entry's finding — `services/engine.py:203-211`, `routes/products.py:76-122`
- §3.3 — revise ×3 — dropped CISO-waiver escape, dropped idempotent dedup (every submission creates a new scan), and coverage never blocks finalization (`ERR_LICENSE_SCAN_INCOMPLETE` is never raised) — `routes/scans.py:60-88`, `services/engine.py:477-490`
- §3.4 — revise ×3 — RESTRICTED carries `SOURCE_DISCLOSURE` regardless of approval; ticket `due_at` = creation + 30 days (not release-date-minus-buffer); withdrawal requester check is vacuous for scan-spawned requests (`requested_by` null) — `services/policy.py:98-99`, `services/engine.py:345`, `routes/approvals.py:131-134`
- §3.5 — revise — finding `remediation_component_id` stays null; the replacement lives on the plan's `target_component_id` — `services/engine.py:598`
- §3.6 — revise — creation guard split (unknown target 404 vs incompatible 400) — `routes/plans.py:74-84`

**Ambiguity pins** (PRD silent; pinned to impl), each with impl anchor:
- §2.3 — insert — limit/offset clamping and non-integer fallback; sort tie-break by `id` — `response.py:56-78`
- §2.6 — insert — vulnerability catalogue filters by `severity` — `routes/vulnerabilities.py:84-86`
- §2.9 & §3.8 — insert — sweep moves only OPEN/IN_PROGRESS tickets to OVERDUE; findings flagged via `deadline_exceeded` — `services/engine.py:502-508,556-561`
- §3.1 — insert — active-BOM definition (newest FINALIZED by created_at/id, else newest DRAFT); recovery clean-board conditions incl. EMBEDDED weak-copyleft — `services/engine.py:51-63,214-256`
- §3.2 — insert — invalid override value → `ERR_INVALID_REQUEST`; rationale stored as `override_rationale` — `routes/components.py:87-93`
- §3.3 — insert ×5 — `manifest_components` body field and per-line spec fields; optional `scan_scope` + invalid → `ERR_INVALID_REQUEST`; resolution matches by exact `package_url` and auto-registers unknown packages; process-next errors (non-QUEUED → 400, unknown → `ERR_SCAN_NOT_FOUND`); `version_label` default `scan-<id8>`; BOM `restricted_components` counts all RESTRICTED entries vs product count excluding approved; supersede flips OPEN/IN_PROGRESS tickets; notice generation requires FINALIZED (`ERR_BOM_NOT_FINALIZED`) and fulfills NOTICE_FILE tickets in OPEN/IN_PROGRESS/OVERDUE; non-FINALIZED archive → `ERR_BOM_NOT_ARCHIVABLE` — `routes/scans.py:42-44`, `services/engine.py:384-458,418-422,93-177,284-298`, `routes/admin.py:40-53`, `routes/boms.py:97-138`
- §3.4 — insert ×3 — STRONG_COPYLEFT non-AGPL in SaaS → `SOURCE_DISCLOSURE`; determination→ticket-type mapping (ATTRIBUTION/SOURCE_OFFER/SOURCE_DELIVERY/COPYLEFT_COMPLIANCE/LICENSE_TEXT); one ticket per entry and one live approval per entry with null-default spawned fields; missing evidence/`waiver_reason` → `ERR_INVALID_REQUEST` — `services/policy.py:87-111`, `services/engine.py:308-351`, `routes/tickets.py:75-97`
- §3.5 — insert ×2 — registration validation errors (`ERR_INVALID_REQUEST`); exact package_url matching, findings in BOMs of any status, vuln+entry dedupe; open-status set OPEN/CONFIRMED/MITIGATED for counts and `vulnerability_severity_max`; confirm CRITICAL pushes only COMPLIANT→AT_RISK; verify evidence/status error pins; false-positive/wont-fix wrong-state → `ERR_FINDING_NOT_OPEN`; finding view embeds `severity`/`cve_id` — `routes/vulnerabilities.py:24-232`, `services/engine.py:19,573-610,128-142`
- §3.6 — insert ×2 — capacity = 365 person-days; complete-plan errors (missing id → 400, unknown scan → `ERR_SCAN_NOT_FOUND`, non-COMPLETED scan → 400) — `routes/plans.py:20,69,159-183`
- §3.7 — insert ×3 — `bom_id`/`release_version` required; notice check is BOM-generated OR gate-attached; finding tallies scoped to the BOM's own entries; zero tickets → 100.00; evaluation sets `notice_file_attached` true; audit-active = INITIATED…REPORT_DRAFT; `bypass_reason` required — `routes/gates.py:47-52,122,160-197,227-229`
- §3.8 — insert ×2 — invalid `audit_type`/missing fields → `ERR_INVALID_REQUEST`; snapshot covers OPEN/CONFIRMED/MITIGATED findings; critical count is per BOM entry with 30-day overdue measured from `due_at` — `routes/engagements.py:48-60,121-125,149-191`
- §4 — insert — admin capabilities (`/_clock`, `/_vulnerability-feed`, `/_scan-worker`) respond 200 — `routes/admin.py:16-53`
