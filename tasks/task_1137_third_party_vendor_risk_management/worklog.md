# Worklog — task_1137_third_party_vendor_risk_management

## Step 1: Create Task Directory — 2026-08-10T23:25:00.000Z

Pre-assigned output folder `tasks/task_1137_third_party_vendor_risk_management` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instruction; treated as done.

## Step 2: Generate Scaffold — 2026-08-11T00:14:00.000Z

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1137_third_party_vendor_risk_management/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1137_third_party_vendor_risk_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1137_third_party_vendor_risk_management/SCAFFOLD_CORNER_DESIGN.yaml`

## Counts
- Entities: **15** (Vendor, VendorEngagement, DueDiligencePackage, Contract, FourthParty, MonitoringCycle, Incident, RemediationPlan, ConcentrationAssessment, ConcentrationBucket, BusinessContinuityTest, AuditExercise, AuditFinding, BoardReport, RiskTierChangeLog)
- State machines: **12** (Vendor, VendorEngagement, DueDiligencePackage, Contract, FourthParty, MonitoringCycle, Incident, RemediationPlan, ConcentrationAssessment, BusinessContinuityTest, AuditExercise, BoardReport)
- Calculations: **8** (dd_aggregate_score, composite_risk_score, tier_posture_derivation, next_monitoring_due, remediation_deadline, concentration_share, exit_readiness_score, board_report_snapshot)
- Validations: **22** (across auth / existence / state / business_safety / business_constraint / business_temporal / business_fiscal / business_referential)
- Endpoints: **79** (incl. POST /tprm/_clock/set_current_utc and GET /tprm/_clock/current_utc)
- Error catalog size: **68**
- Roles: **6** (VendorRelationshipManager, RiskOfficer, BusinessUnitOwner, InternalAuditor, ComplianceDirector, PlatformAdmin)
- Concurrency rules: **3** (all OCC on parent version: DD approve, contract execute, tier change)
- §1.8 difficulty instances: **23** across all 9 Difficulty Rules (≥2 per rule; Rule 5 has 2, Rule 9 has 2, others have 2–3)
- §1.9 corner instances: **45** total (44 active + 1 `excluded_because` stub citing §1.8 instance `bcp_failure_cascade_to_vendor_posture`)
- Lint: **VERDICT: clean lint** — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability.

## Notable design decisions
- **Primary archetype**: Compliance/audit; secondary: multi-party negotiation. Role model is **segregation_of_duties** — submitter ≠ approver on DD; reporter ≠ remediator ≠ verifier on incidents; engagement creator ≠ auditor on audits.
- **Topology**: hybrid (vendor tree for the core, cross-aggregate references from MonitoringCycle/ConcentrationAssessment/BCPTest/AuditExercise back into Vendor and VendorEngagement). Self-referential FourthParty.parent_fourth_party_id supports sub-sub-contractor chains.
- **Difficulty layers**: OCC on three parent entities; dual-variant calculations on three different entity domains (DD score, vendor composite risk, concentration bucket rounding); 3-hop cascade from BCP FAILED → auto-Incident → engagement posture → vendor composite risk; priority-conflict pairs spanning state×safety, safety×fiscal, state×constraint.
- **Rule 8 differentiation**: MonitoringCycle uses half-open geometric windows (`[anchor, anchor+cadence)` — adjacent permitted); AuditExercise uses aggregate-capacity (≤1 active audit per engagement). Two genuinely different interval semantics.
- **Deterministic staleness for OCC negative tests**: use `${var} - 1` arithmetic on a captured version, never a hardcoded literal — per SKILL §1.8 contract item 3c.
- **Logical clock**: mandatory `POST /tprm/_clock/set_current_utc` with startup default `2026-05-01T00:00:00Z`; clock advancement drives MonitoringCycle OVERDUE promotion and Contract EXPIRED promotion as side effects.
- **Boundary literals**: All formula-derived asserts were computed by hand (e.g., DD score 81.00 for tier T3 with scores (80,90,70); 52.50 for vendor composite risk under T1 with SEV_2 + failed BCP; 83.50 for DD with (75,85,95) on T3; posture boundary at 15/40/70 with >= semantics; concentration breach at exactly 25.00; exit readiness floor at 80.00).
- **Corner §1.9 setup caveat acknowledged in design**: the `exit_readiness_at_exactly_80` difficulty instance is documented in its distinguishing_aspect as not directly constructible from integer deductions {50,20,30,15,10}; the instance was pivoted to assert failure at 75 with `ERR_EXIT_READINESS_TOO_LOW`, which is what the lint-clean test_recipe exercises.

## Step 3: Copy Shared Files — 2026-08-11T00:15:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1137_third_party_vendor_risk_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T00:22:00.000Z

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1137_third_party_vendor_risk_management/workspace/PRD.md`

**Line count:** 383 lines

**PRD section list:**
- §1. Introduction
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Common Resource Properties and Identity Conventions
  - 2.5 Nested Resource Retrieval and Path-Parameter Resolution
  - 2.6 Precision, Rounding, and Numeric Representation
  - 2.7 Optimistic Concurrency Control
  - 2.8 Logical Clock and Time-Dependent Rules
  - 2.9 State Enumeration Values
  - 2.10 Soft-Delete and Archival
  - 2.11 Atomicity of Side Effects
- §3. Business Logic & Workflows
  - 3.1 Vendor Onboarding and Inventory
  - 3.2 Engagement Lifecycle from Draft to Active
  - 3.3 Due-Diligence Aggregate Score
  - 3.4 Contracting, Clause Completeness, and Execution
  - 3.5 Fourth-Party Subcontractor Registration
  - 3.6 Vendor Activation, Suspension, Reinstatement, and Exit
  - 3.7 Tier-Cadenced Monitoring
  - 3.8 Incident Intake, Triage, and Remediation
  - 3.9 Engagement Exit and Termination for Cause
  - 3.10 Composite Risk Score and Tier Posture
  - 3.11 Criticality Tier Changes
  - 3.12 Business Continuity Testing
  - 3.13 Right-to-Audit Exercises and Findings
  - 3.14 Concentration Assessment
  - 3.15 Board Reporting
  - 3.16 Validation Ordering Across a Request
- §4. Endpoint Definitions (4-column table: Method, Path, Description, Authorized Roles)
- §5. Error Code Catalogue (2-column table: Error ID, HTTP Status Code)

**Coverage audit (scaffold → PRD mapping):**
- `scenario` → §1 (3 paragraphs)
- `domain_name`, `api_prefix` → title + §1 (`/tprm` mount)
- `response_envelope` → §2.2 (verbatim block) + §2.3 (limit/offset defaults 10/1/100/0, sort by `created_at` ascending, meta fields `limit`/`offset`/`total_count`/`has_more`)
- `entities` (14 entities: Vendor, VendorEngagement, DueDiligencePackage, Contract, FourthParty, MonitoringCycle, Incident, RemediationPlan, ConcentrationAssessment, ConcentrationBucket, BusinessContinuityTest, AuditExercise, AuditFinding, BoardReport, RiskTierChangeLog) → §2.4 (common fields), §2.9 (enum values), scattered through §3.1–3.15 narratives
- `state_machines` (12 machines) → §3.1–3.15 narrative transitions with preconditions and side-effects
- `concurrency_rules` (3 rules: dd-approve, contract-execute, tier-change) → §2.7 + §3.2, §3.4, §3.11 with `expected_engagement_version` / `expected_vendor_version` and `ERR_STALE_VERSION` (412)
- `calculations` (8 rules: dd_aggregate_score, composite_risk_score, tier_posture_derivation, next_monitoring_due, remediation_deadline, concentration_share, exit_readiness_score, board_report_snapshot) → §3.3, §3.7, §3.8, §3.9, §3.10, §3.14, §3.15 with tier weights, thresholds (75/60, 70/40/15, 25.00, 80.00), cadence days (90/180/365/730), severity windows (7/30/90/180), penalties (50/20/30/15/10), histogram buckets [0,15)/[15,40)/[40,70)/[70,100]
- `validations` (19 priority-ordered rules) → §3.16 (ordering prose) + per-trigger error mentions throughout §3
- `endpoints` (60 endpoints) → §4 table; request bodies scattered through §3 narratives
- `errors` (49 error codes) → §5 table; trigger conditions embedded in §2/§3 narratives
- `roles` (6 roles, all `identity: opaque`) → §2.1 with recorded-fields enumeration

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + endpoints[].request_body/query_params/path_params: 107 required, 107 present, 0 missing
Status: PASS

Rule coverage check:
- All state-machine transitions, calculations, validations, OCC rules, side-effects expressed in prose
- Validation priority ordering covered in §3.16
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 606
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Constraint compliance:** Did not read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`. Did not inspect any sibling task directories.

## Step 5: Generate Unit Tests — 2026-08-11T00:55:00.000Z

## Files written

**test_helpers/** (under `/home/ubuntu/github/CodingPRD/tasks/task_1137_third_party_vendor_risk_management/test_helpers/`):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 6 role enum + 21 status/field enums; TypedDicts for all 15 entities (12 full common-field; `ConcentrationBucket`/`AuditFinding`/`RiskTierChangeLog` append-only with only `id`+`created_at`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (62 methods incl. logical-clock pair)
- `api_errors.py` — `ApiErrorId` (59 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions (append-only entities assert absence of `updated_at`/`version`) + `assert_vendor_risk_invariants` (score↔posture threshold agreement)
- `factories.py`, `constants.py` (tier weights, cadences, severity windows, posture/exit/concentration thresholds)
- `test_users.py` — shared headers for all 6 opaque roles + per-user `make_*_headers` builders for SoD threading
- `fixtures.py` — composite helpers: `setup_engagement_with_approved_dd`, `setup_active_engagement`, `setup_active_vendor`, `setup_closed_incident`, `setup_audit_in_fieldwork`, `remediate_incident_to_closed` (approver is a distinct RiskOfficer user; verify uses reporter-id-bound headers), clock/`parse_iso_instant` utilities

**test_suite/**: `conftest.py` + 9 test files (`test_01_vendor_inventory` … `test_09_security_rbac`).

## Test counts per queue
- **Queue A (Difficulty): 46 tests — all 23 instances covered with exactly 2 tests each** (target ≥2 met everywhere).
- **Queue B (Corner): 43 tests across 43 of 44 non-stub instances** (target ≥1 met for every translated instance). The one stub (`cross_cutting_complexity_layers/cascading_side_effects_three_hop_bcp_failure`) was not translated; its `difficulty_instance` pointer resolves to `bcp_failure_cascade_to_vendor_posture` (verified).

## Instances skipped (gaps left as gaps)
- `Corner/state_machines/incident_reopen_limit` — reaching the asserted `reopen_count == 2` state requires closing the incident a second time, i.e. triaging a `REOPENED` incident; PRD §3.8 defines triage only from `OPEN` ("triages an `OPEN` incident (otherwise `ERR_INCIDENT_NOT_OPEN`)"), so the setup path is not uniquely PRD-derivable (a faithful PRD-only implementer may reject the second close). Same reason the second-close leg was dropped from the `incident_open_close_reopen_close_restores_composite_risk_score` translation (its open→close→reopen score sequence 0→8→0→8 is asserted; the non-derivable final close is not).

## Notable adjudications
- `bcp_failure_cascade_to_vendor_posture`: asserted score uses the PRD-derived literal 52.50 ((20+15)×1.5) per the instance's own corrected note; the hop-2 claim (risk_attention_state flips on incident *creation*) contradicts PRD §3.8's triage-flip rule ("...if it was `NORMAL`"), so the second test asserts the PRD-derivable behavior: stays `NORMAL` until triage, then `UNDER_REVIEW`.
- `exit_readiness_at_exactly_80`: used the instance's own pivot (exact-80 unreachable from integer deductions): asserts score 75.00 (PENDING FP −15 + OVERDUE cycle −10) → `ERR_EXIT_READINESS_TOO_LOW`, plus a 100.00 happy-path finalize.
- `derived_field_reconciliation_next_monitoring_due_at`: suspend leg given a PRD-legal trigger (cycle OVERDUE >30 days via clock advance) since PRD requires a triggering condition for suspension.
- Datetime assertions compare parsed instants (not raw strings) to avoid over-constraining ISO 8601 representation while still pinning the derived instant.
- Initial `version == 1` assertions from corner recipes were dropped (PRD never pins the initial version value; only "+1 per mutation" — two-reader divergence).

## Lint / stage-check verdicts
- `ast.parse` clean on all 19 files; `pytest --collect-only` collects **89 tests** with no import errors; pyflakes clean on `test_suite/` (barrel re-export warnings in `__init__.py` are intentional).
- Tag audit: every test has exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line as the final docstring line; all 89 tags resolve to real instances; no stub tagged; no `skip`/`skipif`/`xfail` anywhere.
- Verbatim-citation sweep: every ≥8-word quoted fragment in every test docstring matches PRD.md literally (whitespace-normalized); all asserted `error_id`s are named in PRD prose (§2.1/§2.5/§2.7/§2.8/§3.x/§3.16), not merely the §5 table.

(Orchestrator note: post-hoc pyflakes found one real latent bug — `test_helpers/assertions.py` referenced `HeadquartersRegion` without importing it; orchestrator added the missing import at line 23 before Step 7.)

## Step 6: Generate Implementation — 2026-08-11T00:55:00.000Z

## Files written

- `workspace/implementation/core.py` — Flask app, logical clock (boots at `2026-05-01T00:00:00Z`, never wall-clock), empty in-memory stores (plain dicts keyed by id, zero seeding), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` for lists), `ApiError` + error handlers, `X-User-ID`/`X-User-Role` auth decorator with the six PRD roles, pagination (default 10, min 1, max 100, offset 0), input validators, per-entity serializers (millisecond event timestamps, second-precision scheduling fields, round-trip caller datetimes), and shared business logic (composite risk score with tier multipliers and clamp, tier-posture thresholds >=70/40/15, tier-cadence cycle scheduling 90/180/365/730 with window-overlap guard, tier-weighted DD aggregate with snapshot-at-submit semantics, exit-readiness deductions, remediation deadline with cure-window narrowing).
- `workspace/implementation/routes_vendor.py` — vendor CRUD, activate/suspend/reinstate/exit, OCC-guarded tier-change + tier-change-log, engagement CRUD and initiate-exit/finalize-exit/terminate-for-cause.
- `workspace/implementation/routes_dd_contract.py` — DD package create/submit/begin-review/approve/reject/resubmit (review-round cap 3, supersession, SoD, engagement-version OCC), contract create/list/execute (clause gates in scaffold priority order, fourth-party gate, OCC, DD pin).
- `workspace/implementation/routes_fp_cycle.py` — fourth-party create/acknowledge/reject with parent-chain validation and REGULATED_PII tier gate; monitoring-cycle list/begin/complete (on-time vs late by clock)/waive (TIER_4 only).
- `workspace/implementation/routes_incident.py` — incident file/triage/reopen (cap 2, reporter-only), remediation plan draft/submit/approve (atomic SUBMITTED→APPROVED→IN_EXECUTION)/reject (reverts incident to TRIAGED)/submit-verification/verify (reporter-only), all SoD rules.
- `workspace/implementation/routes_risk.py` — concentration assessments (bucket compute, round-then-compare 25.00% breach, supersession, share-DESC/key-ASC ordering), BCP tests (RTO/RPO outcome, TIER_1 FAIL auto-raises SEV_2 OUTAGE incident), audit exercises and findings (SoD vs engagement creator, right-to-audit gate, single-active-audit capacity, SEV_1/SEV_2 auto-incident raise at issue-findings, close blocked until raised incidents CLOSED), board reports (half-open window overlap guard, full snapshot_payload with risk histogram).
- `workspace/implementation/routes_clock.py` — `POST /tprm/_clock/set_current_utc` (PlatformAdmin; promotes SCHEDULED/IN_PROGRESS cycles with `due_at < now` to OVERDUE with vendor posture recompute, and EXECUTED contracts past expiry on non-ACTIVE engagements to EXPIRED) and `GET /tprm/_clock/current_utc` (all six roles).
- `workspace/implementation/app.py` — entry point; imports route modules, runs `app.run(host="0.0.0.0", port=int($PORT or 10000), threaded=True)`.
- `workspace/implementation/start.sh` — executable; guarded dependency install (`if ! python3 -c "import flask"`), then `exec python3 app.py` in the foreground.
- `workspace/implementation/requirements.txt` — `flask>=2.2,<4`.

## Endpoint count implemented

**79 endpoints** — the complete SCAFFOLD.yaml §1.5 endpoint table.

## How to start the server

```bash
cd tasks/task_1137_third_party_vendor_risk_management/workspace/implementation
PORT=10000 bash start.sh    # PORT optional, defaults to 10000; binds 0.0.0.0, foreground via exec
```

Verified working via `bash start.sh`: fresh boot shows empty stores (vendor list `total_count: 0`), clock at `2026-05-01T00:00:00Z`, correct error envelope, bound on all interfaces.

## Route-table cross-check vs SCAFFOLD.yaml

Programmatically compared `app.url_map` (all 6 route modules imported) against the scaffold `endpoints:` list: **79 scaffold (method, path) pairs declared, 79 registered, 0 missing, 0 extra — exact MATCH.**

(Orchestrator independent re-verification before Step 7: 79 declared / 79 registered / 0 missing / 0 extra — MATCH confirmed.)

## Validation performed

- 90 smoke assertions across two end-to-end scripts, all passing, covering: auth 401/403 ordering, duplicate-key 409s, DD weighted scores per tier (81.00 verified for TIER_3 80/90/70), FAIL-outcome approve gate, reject/resubmit round cap, SoD self-approve/self-remediate/self-plan-approve/verify-not-reporter/auditor-is-creator, OCC 412 on DD approve / contract execute / tier-change, contract clause gates (SLA/audit/exit-plan) and FP-pending gate, vendor activation cycle anchoring (`2026-05-01` + 90d = `2026-07-30` for TIER_1), cycle complete/waive chains, cure-window narrowing (30d SEV_2 → 20d), composite score arithmetic (e.g. SEV_2+BCP-fail on TIER_1 = 35 × 1.5 = 52.5 ESCALATED), suspend/reinstate/exit/terminate-for-cause with contract cascade, archived-vendor hidden/flagged listing and legal_name reuse, clock-driven OVERDUE and EXPIRED promotions, concentration buckets (100% EMEA breach), board-report snapshot contents, window-overlap 422, and pagination meta.

## Step 7: Run/Fix Loop — 2026-08-11T01:05:00.000Z

### Iteration 1 (8-round parallel sweep)
- Result: **88/89 in all 8 rounds** — one deterministic failure, zero flakiness.
- Failing test: `test_01_vendor_inventory.py::TestVendorSoftArchive::test_exited_vendor_excluded_from_default_listing`
  - Failure: `POST /tprm/vendors/{id}/exit` returned 409 `ERR_VENDOR_NOT_ACTIVE`.
  - STEP 1 (coverage/derivability): PRD §3.6 verbatim requires "Vendor exit moves `ACTIVE → EXITED`. It requires the vendor to be `ACTIVE`"; §2.10 verbatim covers the archived-listing rule asserted. Covered + uniquely derivable — test stays.
  - STEP 2 (test consistency): TEST BUG — the test set up its precondition with `setup_active_engagement`, whose documented contract leaves the vendor in `ONBOARDING` (vendor activation is a separate RiskOfficer step per PRD §3.6). The PRD-faithful implementation correctly rejected the exit. Sibling test `test_04::test_exited_vendor_is_terminal` performs the identical flow correctly via `setup_active_vendor`.
  - Fix (test_suite): swapped `setup_active_engagement` → `setup_active_vendor` in `TestVendorSoftArchive.test_exited_vendor_excluded_from_default_listing` (import + call site). With the vendor ACTIVE, the exit flow (initiate-exit → finalize-exit at readiness 100 → vendor exit) satisfies every PRD §3.6/§3.9 gate.

### Iteration 2 (8-round parallel sweep, after fix)
- Result: **89/89 passed in all 8 rounds** (rounds 1–8 all clean). No deletions, no implementation changes required.

### Step 7 subagent exit summary (verbatim)
- **Iterations run**: 2 (iteration 1: 88/89 in all 8 rounds, one deterministic failure, zero flakiness; iteration 2 after fix: **89/89 in all 8 rounds — clean exit**).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none — the fixture library itself was correct; the bug was at the call site in the test suite.
- **Fixes applied to `test_suite/`**: `test_01_vendor_inventory.py` — `TestVendorSoftArchive.test_exited_vendor_excluded_from_default_listing` now builds its precondition with `setup_active_vendor` instead of `setup_active_engagement` (import line 11 + call site line 220). Why: PRD §3.6 verbatim gates vendor exit on the vendor being `ACTIVE` ("Vendor exit moves `ACTIVE → EXITED`. It requires the vendor to be `ACTIVE`"), but `setup_active_engagement` deliberately leaves the vendor in `ONBOARDING`, so the PRD-faithful implementation correctly returned 409 `ERR_VENDOR_NOT_ACTIVE`. The asserted rule itself (archived vendor hidden from default listing, surfaced via `include_archived`) is verbatim in PRD §2.10 and stays fully asserted.
- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful on every failing request.

## Step 8: Finalize PRD — 2026-08-11T01:12:00.000Z

`PRD_FINALIZED.md` has been produced at `/home/ubuntu/github/CodingPRD/tasks/task_1137_third_party_vendor_risk_management/workspace/PRD_FINALIZED.md` as a verbatim copy of `PRD.md` with **zero edits**.

## Summary

**Line counts / delta**: `PRD.md` = 383 lines, `PRD_FINALIZED.md` = 383 lines, 0.0% delta (byte-identical, confirmed by `diff`).

**Changes**: none.

### Justification for zero edits

The single `<step_7_diff>` item is a pure test-fixture fix (`test_01_vendor_inventory.py:11,220`: `setup_active_engagement` → `setup_active_vendor`), with zero implementation changes and zero deletions. Both behaviors the fixed test exercises are already uniquely and verbatim determined by the PRD, and the implementation is PRD-faithful on both:

1. **Vendor-exit ACTIVE gate** — PRD §3.6 (line 150) states verbatim: "Vendor exit moves `ACTIVE → EXITED`. It requires the vendor to be `ACTIVE`". The implementation enforces exactly this at `routes_vendor.py:149-150` (`if v['status'] != 'ACTIVE': err('ERR_VENDOR_NOT_ACTIVE', 409, ...)`). The old fixture (`setup_active_engagement`, `test_helpers/fixtures.py:184-198`) deliberately leaves the vendor in `ONBOARDING`, so the PRD-faithful 409 was correct and the fixture was wrong. No PRD silence, no PRD/impl mismatch.
2. **Archived-vendor listing rule** — PRD §2.10 (line 98) states verbatim that `archived_at` is set on `EXITED` and that "List endpoints accept an `include_archived` flag to surface archived vendors". Matches `routes_vendor.py:55-58` (default filter excludes `archived_at` non-null) and `routes_vendor.py:158` (exit sets `archived_at=now()`).

### Candidate-edit assessment (pre-edit search log for the edit that was considered and rejected)

- **(a) Subject considered**: §3.6 exit paragraph omits an inline error name for the ACTIVE clause while its sibling clauses name theirs — candidate edit would have inserted "(otherwise `ERR_VENDOR_NOT_ACTIVE`, HTTP 409)".
- **(b) Impl paths enumerated**: `routes_vendor.py:100-101` (suspend ACTIVE gate → same error), `routes_vendor.py:149-150` (exit ACTIVE gate), `routes_vendor.py:158` (exit side effects), `routes_vendor.py:51-65` (list + `include_archived`), `routes_vendor.py:32` (archived excluded from `legal_name` uniqueness), `routes_risk.py:107` and `routes_risk.py:467` (archived excluded from concentration aggregation and board-report counts), `core.py:346` (`archived_at` serialization). Cross-checks: PRD error catalog (line 322, `ERR_VENDOR_NOT_ACTIVE` → 409); PRD §3.6 suspension paragraph and §3.7 cycle-begin rule both map the identical condition phrase "requires the vendor to be `ACTIVE`" to `ERR_VENDOR_NOT_ACTIVE`, HTTP 409; passing test `test_04_vendor_lifecycle_monitoring.py:86-107` asserts this error mapping via the terminal-state lockdown test.
- **(c) Outcome**: edit rejected. The error-code mapping is already uniquely determined by the error catalog plus two identical in-PRD precedents (suspension §3.6, cycle-begin §3.7), so there is no PRD silence for an implementer to resolve differently; and per HARD SCOPE the Step 7 fix revealed only a fixture bug, not a PRD gap. Under the NO-NEW-MISMATCH rule, adding inline wording to §3.6 risked narrowing a section already consistent with every enumerated path, with zero behavioral upside.

## Step 9: Complete PRD — 2026-08-11T01:14:00.000Z

All edits applied and verified. PRD_COMPLETED.md is complete: 27 lines revised in place (28 edit operations; two §3.13 pins landed in the same paragraph line).

## Summary

**Source**: `PRD_FINALIZED.md` (383 lines, 58,169 chars) → `PRD_COMPLETED.md` (383 lines, 63,132 chars; **+4,963 chars**, 0 net line change — all in-paragraph inserts/revisions, no new sections).

**Counts**: 24 ambiguity-pins, 5 mismatch-revisions.

**Changes** (section — op — class — what — impl ref):

- §2.1 — insert — ambiguity — unknown `X-User-Role` value counts as malformed → `ERR_UNAUTHENTICATED` 401 — core.py:184
- §2.3 — insert — ambiguity — pagination bound/non-integer violations → `ERR_INVALID_REQUEST` 400; `has_more` = offset+returned < total_count; sort ties by creation order; full per-endpoint filter enumeration — core.py:205-226, 138; list handlers in routes_*.py
- §2.4 — insert — ambiguity — caller-supplied server-managed fields ignored on all creation endpoints — core.py:282-288
- §2.6 — insert — ambiguity — caller-supplied datetimes echoed round-trip (second precision, or ms when sub-second supplied); offsets normalized to UTC, naive read as UTC — core.py:79-103
- §2.8 — insert — ambiguity — clock settable forward or backward with promotions evaluated on every set; response fields `new_current_utc` / `current_utc` — routes_clock.py:11-42
- §2.10 — revise — ambiguity — `include_archived` scoped to the vendor list; accepted values `true`/`1`/`yes` case-insensitive; archived excluded by default — routes_vendor.py:54-58
- §3.2 — insert — ambiguity — engagement creation allowed whatever the vendor's `status`; `service_summary` may be empty — routes_vendor.py:211-235
- §3.2 — insert — ambiguity — resubmit re-stamps `submitted_by_user_id`; scores not carried keep previous values — routes_dd_contract.py:156-177
- §3.4 — **revise — mismatch** — execution check order corrected to impl: DRAFT → SLA terms → audit clause → exit plan → fourth parties → OCC last (PRD had OCC second) — routes_dd_contract.py:262-286
- §3.5 — insert — ambiguity — `service_provided` may be empty; declaration allowed at any lifecycle point — routes_fp_cycle.py:31-65
- §3.6 — insert — ambiguity — suspension with no trigger met → `ERR_INVALID_STATE` 409 — routes_vendor.py:111-113
- §3.6 — **revise — mismatch** — replaced "because no new cycles are scheduled while suspended" (impl's waive still schedules while suspended) with: completion-triggered successor scheduling suppressed while vendor not `ACTIVE` — routes_vendor.py:114; routes_fp_cycle.py:176-205
- §3.6 — **revise — mismatch** — reinstatement reuses an existing live cycle's `due_at` rather than always scheduling anew; pinned error names `ERR_OPEN_SEV1_INCIDENT`/`ERR_INVALID_STATE` — routes_vendor.py:127-141
- §3.6 — insert — ambiguity — vendor exit from non-`ACTIVE` → `ERR_VENDOR_NOT_ACTIVE` 409 — routes_vendor.py:149-150
- §3.7 — **revise — mismatch** — cycle window defined as [anchor, `due_at`) and overlap checked only against cycles currently `SCHEDULED`/`IN_PROGRESS` (PRD said "any prior non-`WAIVED` cycle") — core.py:600-620
- §3.7 — **revise — mismatch** — successor cycle scheduled on completion only while vendor `ACTIVE`; otherwise none and `next_monitoring_due_at` unchanged — routes_fp_cycle.py:175-187
- §3.7 — insert — ambiguity — waive updates `next_monitoring_due_at` only while vendor `ACTIVE` — routes_fp_cycle.py:202-204
- §3.8 — insert — ambiguity — incident filing allowed whatever the engagement's `lifecycle_status` — routes_incident.py:32-43
- §3.8 — insert — ambiguity — `plan_summary` may be empty — routes_incident.py:121
- §3.9 — revise — ambiguity — 30-point exit-readiness deduction pinned: vendor `TIER_1_CRITICAL` and no `EXECUTED` contract with `has_exit_plan_section`, including no `EXECUTED` contract at all — core.py:684-687
- §3.11 — insert — ambiguity — tier change permitted in any vendor status incl. same-tier (still logged, version still bumps); `next_monitoring_due_at` cleared to null when vendor not `ACTIVE` — routes_vendor.py:183-197
- §3.12 — insert — ambiguity — BCP scheduling allowed whatever the engagement's `lifecycle_status` — routes_risk.py:178-179
- §3.12 — insert — ambiguity — auto-created `OUTAGE` incident has `reported_by_user_id` = `system`, `detected_at` = current instant — routes_risk.py:247-250; core.py:660-670
- §3.13 — insert — ambiguity — finding `description` may be empty — routes_risk.py:330
- §3.13 — insert — ambiguity — auto-raised `REGULATORY_FINDING` incidents: reporter `system`, `detected_at` = issuance instant — routes_risk.py:381-384
- §3.14 — insert — ambiguity — `breach_bucket_keys` listed in the same share-desc/key-asc sorted order — routes_risk.py:125-135
- §3.15 — insert — ambiguity — histogram keys pinned to `0-15`, `15-40`, `40-70`, `70-100` — routes_risk.py:475-485
- §3.16 — insert — ambiguity — generic payload validation defined: documented fields present and of documented JSON type, required strings non-empty unless prose permits empty, JSON booleans rejected for int/number fields — core.py:229-276
- §4 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` 404; defined path with unsupported method → `ERR_INVALID_REQUEST` at HTTP 405 — core.py:152-159

Everything else in the impl (endpoint set, RBAC per endpoint, state machines, all calculation formulas and weights, error catalogue usage, OCC endpoints, SoD rules, clock promotion semantics, serializer field shapes) was already uniquely pinned by PRD_FINALIZED.md and left untouched.
