# Worklog — task_1170_business_continuity_disaster_recovery

## Step 1: Create Task Directory — 2026-08-11T08:00:43.000Z

Task directory `tasks/task_1170_business_continuity_disaster_recovery/` and its `workspace/` subdirectory were pre-assigned and already exist; Step 1 auto-index scan skipped per instructions. Scenario: Business Continuity & Disaster Recovery Program (enterprise resilience office).

## Step 2: Generate Scaffold — 2026-08-11T09:20:30.000Z

All three scaffold artifacts are generated, on disk, and clean-linted.

## Summary — task_1170 Business Continuity & Disaster Recovery Program

**Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1170_business_continuity_disaster_recovery/`):**

| File | Size | Lines | Content |
|---|---|---|---|
| `SCAFFOLD.yaml` | 126,995 B | 1,397 | §1.0–§1.7 (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 95,206 B | 1,665 | single key `scaffold_difficulty_design` (§1.8) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 110,192 B | 1,892 | single key `scaffold_corner_design` (§1.9) |

**Counts:**
- **Entities: 19** — Contact, Process, Bia, Plan, PlanSection, Dependency (DAG edges), ThirdParty, Assessment, AlternateSite, SiteReservation, Exercise, Finding, RecoveryCapability, ValidationRun, Gap, CommNode (self-referential tree), Activation, Notification, Attestation
- **State machines: 16** (all entities except Contact/PlanSection/Dependency), incl. cyclic BIA revision loop with SoD ratchet, plan revert loop, compound capability lifecycle, bubble-up Activation/Notification — plus **3 OCC concurrency rules** (plan/exercise PUT, stale-version 412)
- **Calculations: 9** — incl. dual-variant BIA criticality (TIER_1 uplift freeze) and vendor continuity (event-driven discount), pinned-order rounding (per-reservation-then-sum site utilization), pinned evaluation-order attestation readiness with a >=70 sign gate, topological blast radius, gap pressure with critical-overdue doubler
- **Endpoints: 112** (incl. `POST /resilience/_clock/set_current_utc` with mandated default 2026-05-01T00:00:00Z)
- **Validations: 30** ordered priorities; **Errors: 56** (all referenced); **Roles: 10** (9 entity-backed Contact roles + opaque ResilienceAdmin, segregation-of-duties model)
- **§1.8 instances: 18** (2 per rule × 9 rules, all differentiation clauses honored — different entity domains, modes (a)/(b)/(c), error-category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities)
- **§1.9 instances: 32** (31 active + 1 excluded_because stub), across all nine claim-extraction sections
- **661 test-recipe calls** scanned by `scaffold_lint.py` → **VERDICT: clean lint**

**Key design decisions for harder-than-expert difficulty:** graph topology with DAG cycle guards + self-referential comm tree; adoption-pinning where BIA approval silently re-targets DRAFT plans (feeds a genuine OCC stale-version test); a depth-3 cascade (exercise complete → validation run → capability flip → gap creation) plus a depth-2 supersede/adoption cascade from a different trigger; supersede cascade deliberately bypassing the manual retire guard so in-flight exercises fail at completion; dual rounding-order trap pinned at 50.1 vs 50.0; inclusive-boundary chain (plan approve equality passes → exercise result boundary → readiness exactly-70 signs); four SoD gates on decide/finalize/release/revoke. All numeric asserts were pre-computed from the formulas (e.g., BIA 50.40 → 57.96 FINAL; vendor score 72 → 57 EVENT_DRIVEN; readiness 70 pass / 65 fail; pressure 7 → 30 with doubler).

## Step 3: Copy Shared Files — 2026-08-11T09:29:43.000Z

Copied ./INSTRUCTION.md to tasks/task_1170_business_continuity_disaster_recovery/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-11T09:48:18.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1170_business_continuity_disaster_recovery/workspace/PRD.md` — 440 lines, exists and verified.

**Section list:**
- §1 Introduction (3 paragraphs: pain points → system scope → design commitments)
- §2 Global Specifications: 2.1 RBAC (10 roles with exact spellings + per-role identity prose — `ResilienceAdmin` opaque, 9 roles entity-backed via `Contact`), 2.2 API Response Structure (**byte-identical verbatim** to the canonical block, diff-verified), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Program Clock (default `2026-05-01T00:00:00Z`, `to_iso8601`, recomputation side effects), 2.5 Common Resource Properties (incl. `Dependency`/`Notification` carrying only `id`+`created_at`; ValidationRun supersede bumps `updated_at` but not `version`), 2.6 Cascading Consistency, 2.7 Precision/Rounding, 2.8 OCC (both rules: `expected_plan_version`/`expected_exercise_version` → `ERR_STALE_VERSION` 412), 2.9 Nested Retrieval (left-to-right, all 20 path params mapped to their `ERR_*_NOT_FOUND`), 2.10 Validation Precedence (all 30 scaffold validations expressed as a 15-layer ordered walk), 2.11 SoD + Uniqueness
- §3 Business Logic: 3.1 Processes/Dependencies/blast radius, 3.2 BIA lifecycle + dual-variant criticality score, 3.3 Plans/Sections/adoption pin, 3.4 Third-parties/Assessments, 3.5 Sites/Reservations/utilization (pinned per-reservation-then-sum order), 3.6 Exercises/Findings (failover cascade), 3.7 Capabilities/ValidationRuns/Gaps (freshness, gap pressure), 3.8 Comm trees/Activations (SEV→criterion mapping, fan-out, ack coverage, empty-tree guard), 3.9 Attestations (10-step readiness formula, sign gate ≥70, immutable snapshot, revoke SoD)
- §4 Endpoint table: **112 rows**, 4 columns (Method, Path, Description, Authorized Roles)
- §5 Error catalogue: **56 rows**, 2 columns (Error ID, HTTP Status)

**Coverage self-audit (all three hard contracts PASS):**
- **Contract 1 (Field-Name Coverage):** entities[].fields 126/126, endpoints[].input 110/110, path params 20/20, pagination fields 4/4 — 0 missing (audit run mechanically against the parsed scaffold YAML; two initial misses — `full_name`, and the `EXITED`/`DEACTIVATED` state literals — were repaired and the audit re-run to zero).
- **Contract 2 (Rule Coverage):** all 30 priority-ordered validations expressed (§2.10 layered walk + trigger-adjacent prose in §3); both OCC rules with endpoint + field + `ERR_STALE_VERSION`/412; all 16 state machines' transitions with preconditions, error ids, and side effects (incl. supersede hop, adoption refresh, recalculation refresh, vendor-exit/site-retire capability flips with 90-day HIGH gaps, failover completion cascade with empty-pool silence, finding verify/reject gap disposition, no-auto-verify non-cascade); all 9 calculations in precise reconstructible prose (weights 45/25/20/10 and 15% TIER_1 uplift; 60/40 blend with 10- and 5-point per-hour penalties and 15-point EVENT_DRIVEN discount; BFS blast radius ordered by discovery-edge `created_at`; pinned utilization rounding order; inclusive exercise/run boundaries; 10-step readiness with pinned evaluation order; 4/3/2/1 gap weights with overdue doubling and CRITICAL-overdue total doubling; half-up whole-percent coverage); all endpoint side effects and applies_to scopes covered; 56/56 error ids appear in §2/§3 prose; 38-point high-risk rule spot-check passed.
- **Contract 3 (§3 Path Purity):** 899 backticked tokens scanned in §3 — 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. Pseudocode/fuzzy-word scan clean; §2.2 verified byte-identical to `section-2.2-response-structure.md`.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate Unit Tests — 2026-08-11T10:26:00.000Z

Test generation complete for task_1170. All stage gates pass.

## test_helpers/ (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1170_business_continuity_disaster_recovery/test_helpers/`)

- `types.py` — 10 role enum + 16 status enums + 19 entity TypedDicts (Dependency/Notification correctly omit `updated_at`/`version` per `common_fields: false`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all ~75 routes: clock, contacts, processes, BIAs, plans+sections, dependencies, third-parties, assessments, sites+utilization, reservations, exercises, findings, capabilities, validation-runs, gaps, comm-nodes, activations, notifications, attestations)
- `api_errors.py` — `ApiErrorId` (57 members) + HTTP status map registered via `set_error_http_status_map` (ERR_VALIDATION registered 400; 422 variants pass `expected_status` explicitly)
- `assertions.py` — per-entity `assert_*` structural checkers
- `factories.py` — input-field-only payload factories for all 18 creatable entities
- `constants.py` — calculation constants (TIER1_UPLIFT 0.15, EVENT_DRIVEN_DISCOUNT 15, sign gate 70, gap weights, etc.)
- `test_users.py` — `TEST_USERS` shared constants + `make_<role>_headers(user_id)` builders for all 9 entity-backed roles
- `fixtures.py` — composite helpers: contact/process/BIA lifecycle (`create_approved_bia`), plan lifecycle (`create_approved_plan` with the 3 required sections), exercise lifecycle, validated capabilities, vendors/sites/reservations, comm trees, activations, plus two full-program scenarios (`setup_approved_program`, `setup_attestation_scenario` with exact overdue/fresh gap control, `setup_activation_ready`)
- `__init__.py` — barrel export

## test_suite/ (8 test files + conftest.py; 67 tests collected by pytest)

| File | Tests | Queue A | Queue B |
|---|---|---|---|
| test_01_scoring_variants.py | 5 | 4 | 1 |
| test_02_plans_and_bias.py | 16 | 12 | 4 |
| test_03_exercises_and_validation.py | 14 | 8 | 6 |
| test_04_sites_and_reservations.py | 6 | 6 | 0 |
| test_05_findings_gaps_capabilities.py | 6 | 2 | 4 |
| test_06_crisis_comms.py | 7 | 0 | 7 |
| test_07_attestations.py | 6 | 4 | 2 |
| test_08_registry_graph_and_envelope.py | 7 | 0 | 7 |

**Queue A (Difficulty): 36 tests** — all 18 instances × ≥2 tests. **Queue B (Corner): 31 tests** — all 31 non-stub instances × 1 test.

## Skipped instances

- `Corner/state_machines/finding_verify_closes_remediation_gap_stub` — `excluded_because:` stub, not translated per spec; cross-reference to `Difficulty/compensating_invariant/finding_verify_closes_gap_backlog_invariant` verified to resolve.

No instance failed the PRD-first filter — all 49 non-stub instances had verbatim PRD coverage and unique derivability.

## Judgment call (1 deviation from a recipe)

`Difficulty/compensating_invariant/site_seats_reserve_release_capacity_invariant`: the recipe's over-capacity attempt reused process P2, which would simultaneously trip same-process overlap (ERR_SITE_WINDOW_OVERLAP) and capacity (ERR_SITE_CAPACITY_EXCEEDED) — both live in PRD §2.10 layer 12 with no pinned intra-layer order, failing unique derivability. I redirected the attempt to a third process P3 (same arithmetic 3+4+2=9>8) so only the capacity rule can fire.

## Verification verdicts

- **Syntax/imports**: all 18 files parse; `test_helpers` imports cleanly; every `api_client.*` call and `test_helpers` import in tests resolves.
- **Completeness audit (C4)**: 67 tests, each with exactly one `Design:` tag; all tags resolve to real instances; difficulty ≥2/instance and corner ≥1/instance confirmed programmatically — PASS.
- **PRD citation pass (C1–C3)**: 111 quoted citations extracted from docstrings; all verbatim-match `workspace/PRD.md` (two ellipsis-bearing quotes were caught and rewritten to full verbatim spans) — PASS.
- **Forbidden markers**: zero `skip`/`skipif`/`xfail`; zero "scaffold" references in generated code — PASS.
- **pytest collection**: 67 tests collected without a server (import-clean) — PASS.

## Step 6: Generate Implementation — 2026-08-11T10:26:00.000Z

Implementation complete and verified.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1170_business_continuity_disaster_recovery/workspace/implementation/`

**Files (12):**
| File | Size | Contents |
|---|---|---|
| `start.sh` | 396 B | Executable launcher; guarded pip install (`import flask` check), `exec python3 app.py` in foreground |
| `requirements.txt` | 11 B | `flask>=3.0` |
| `app.py` | 1.7 KB | Flask app, global request lock, error handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `core.py` | 10.0 KB | In-memory `Store` (19 dicts, no seeding), logical clock (default `2026-05-01T00:00:00Z`), envelope (`meta`/`response_type`/`data`), auth (`X-User-ID`/`X-User-Role`, 10 roles, entity-backed SoD identity), pagination (`limit`/`offset`/`total_count`/`has_more`, 10/1/100/0), field validators, monotonic tick timestamps (3-fraction ISO8601) |
| `calc.py` | 19.1 KB | All 9 calculations (BIA dual-variant score with TIER_1 15% uplift, vendor continuity score with EVENT_DRIVEN −15, blast radius BFS, pinned-order site utilization, exercise result, validation-run result, attestation readiness with pinned 10-step order and ≥70 gate, gap pressure with critical-overdue doubling, ack coverage) + cascades (run supersede, capability flip, auto-gap creation) |
| `serializers.py` | 6.7 KB | Field-whitelisted views; computed-on-read refresh of `overdue`, `meets_bia`, `validation_freshness`, DRAFT `readiness_score`, `coverage_pct`; Dependency/Notification emit only `id`+`created_at` (no `updated_at`/`version`) |
| `routes_registry.py` | 12.8 KB | Clock, contacts, processes + lifecycle/retire cascade, 6 process sub-collections, dependencies (DAG + self-loop) |
| `routes_analysis.py` | 20.7 KB | BIAs (PROVISIONAL/FINAL, submit/decide, supersede hop + adoption re-pin + DRAFT-assessment recalc), plans (OCC `expected_plan_version`, section gate, approve supersede cascade, guarded retire), sections CRUD |
| `routes_vendor_site.py` | 17.3 KB | Third parties (exit cascade), assessments (SoD finalize, miss-RTO auto-gap), sites (retire cascade), reservations (capacity → same-process overlap → contract checks), utilization, SoD release |
| `routes_exercise.py` | 14.0 KB | Exercises (FAILOVER closed-interval disjointness, OCC `expected_exercise_version`, completion cascade creating ValidationRun), findings (remediate auto-gap, verify closes gap, reject → ACCEPTED_RISK) |
| `routes_capability.py` | 10.4 KB | Capabilities (typed ref validation, mark-remediated gate), standalone runs (`ERR_CAPABILITY_TARGETS_UNKNOWN`), gaps lifecycle + aggregate refresh |
| `routes_crisis.py` | 18.3 KB | Comm nodes (root/sibling/cycle/children integrity), activations (SEV→criterion map, BFS fan-out, empty-tree → ACKNOWLEDGED), notification ack (token, bubble-up), attestations (readiness gate, immutable snapshot, SoD revoke) |

**Endpoints:** 112 routes implemented — matches the PRD §4 table count of 112 exactly.

**Key contract choices:** validation follows the PRD §2.10 15-layer precedence (auth → FK existence → shape → state → SoD → safety → uniqueness → gating → guards → temporal → approval targets → cross-ref → OCC last); SoD endpoints (`bias/{id}/decide`, `assessments/{id}/finalize`, `site-reservations/{id}/release`, `attestations/{id}/revoke`) additionally require `X-User-ID` to resolve to an existing Contact (else 403); sign gate is `readiness >= 70` per PRD prose (overrides scaffold's `> 70`); cross-reference `ERR_VALIDATION` is 422 on `POST /findings` and `POST /recovery-capabilities`, 400 elsewhere.

**Boot smoke test:** `bash start.sh` with `PORT` set boots in ~1 s, binds 0.0.0.0, serves the envelope correctly. Verified the per-test-server contract: kill → relaunch via `bash start.sh` → store empty, clock back at `2026-05-01T00:00:00Z`. Two functional suites passed end-to-end: a 100+-assertion workflow pass (auth 401/403, duplicates, MTPD 422, BIA score 170.0→195.5 FINAL with tier uplift, OCC 412, section gate, vendor/site/run cascades, finding remediate→verify gap closure, comm tree root-uniqueness 409, SEV2+CRITERION_B 422, ack token 403/re-ack 409, coverage 100, utilization 16.7, release SoD 403, blast radius, cycle/self-loop 422, readiness 90 sign, revoke SoD 403, clock set → freshness STALE) and an edge-case pass (error envelope shape, nested left-to-right 404, 204 no-body DELETE, exercise OCC 412, FAILOVER completion cascade with run+gap creation, retire guard 409, plan supersede cascade, and the pinned per-reservation-rounding utilization case: capacity 6 with three 1-seat reservations → 50.1, not 50.0). All test servers were stopped and `__pycache__` removed.

Orchestrator route-parity check: 112/112 SCAFFOLD.yaml (method, path) pairs registered in the Flask app (only extra is Flask's built-in /static/ handler). pytest collection from task root: 67 tests collected.

## Step 7: Run Tests and Iterate — 2026-08-11T10:37:00.000Z

Clean 8/8-round sweep achieved. Summary:

## Summary

- **Iterations run:** 2 (first sweep: 63/67 in all 8 rounds, same 4 deterministic failures; second sweep after fixes: 67/67 × 8 rounds, zero failures, zero flakiness).

- **Tests deleted:** none. All 4 failing tests traced to verbatim PRD rules with unique derivability.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1170_business_continuity_disaster_recovery/test_suite/test_02_plans_and_bias.py` — added `approve_plan` to the `from test_helpers import (...)` list. Three tests (`test_plan_resubmit_and_approve_records_approved_version`, `test_plan_approve_succeeds_after_target_bia_approved`, `test_plan_approval_allows_committed_rto_equal_to_target`) called the fixture helper bare but the file's explicit import list omitted it, producing `NameError`. Pure mechanical test bug; the assertions themselves are PRD-verbatim (§3.3 `approved_version_no`, §3.3 target-BIA approval gate, §3.3+§2.7 inclusive boundary).

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1170_business_continuity_disaster_recovery/workspace/implementation/routes_crisis.py` — `ack_notification()`: reordered guards from (activation-state → token → notification-SENT) to (token → notification-SENT → activation-state). PRD §3.8 pins the guard order in a single sentence ("The token must match… the notification must still be `SENT` (`ERR_NOTIFICATION_ALREADY_ACKED` on a repeat), and the owning activation must still be in `ACTIVE` or `ALL_NOTIFIED`…"), and §2.10 layer 10 lists token-match before ack-only-once. The old order made a replay ack on a single-notification activation (which bubbles to `ACKNOWLEDGED` on the first ack) return `ERR_INVALID_STATE` instead of the PRD-assigned `ERR_NOTIFICATION_ALREADY_ACKED`. No other test depends on the old order, and the deactivated-activation path still yields `ERR_INVALID_STATE` when the notification is genuinely still `SENT`.

Orchestrator verification: all 8 results.{1..8}.json on disk show passed=67 total=67 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-08-11T10:44:00.000Z

Both edits applied cleanly; the diff shows exactly the two intended line modifications.

## Summary

**Line counts:** PRD.md 440 lines; PRD_FINALIZED.md 440 lines; 0% delta (two lines revised in place, no insertions/deletions).

**Changes:**
- §2.10 (layer 10) — revise — appended the owning-activation-still-`ACTIVE`-or-`ALL_NOTIFIED` guard (`ERR_INVALID_STATE`, HTTP 409) to the layer-10 list after the once-only guard and pinned "the three acknowledgement guards are evaluated in that order" — `implementation/routes_crisis.py:346-355`.
- §3.8 — revise — changed "The token must match…" to "Its guards are evaluated in this fixed order: the token must match…", making the token → notification-`SENT` → activation-state guard order explicit — `implementation/routes_crisis.py:346-355`.

The other step_7 item (missing `approve_plan` import in `test_suite/test_02_plans_and_bias.py`) was a pure fixture bug — no PRD edit.

**Rationale for editing at all:** §3.8 listed the three guards as a plain conjunction (no explicit ordering), and §2.10 layer 10 omitted the activation-state `ERR_INVALID_STATE` guard entirely — so an implementer could legitimately file that guard under layer 6 (state legality, "state-guarded writes") and, per §2.10's lower-layer-masks-higher rule, check activation state before the token/once-only guards. That is exactly the old implementation's order, which returned `ERR_INVALID_STATE` instead of the intended `ERR_NOTIFICATION_ALREADY_ACKED` on a replay ack. The PRD therefore admitted the old order and needed minimal tightening.

**Per-edit pre-edit search log** (both edits share one subject, searched once before either was committed):
- (a) Subject: evaluation order and precedence-layer placement of the three acknowledgement guards (token match, notification `SENT`, owning activation `ACTIVE`/`ALL_NOTIFIED`) on `POST /resilience/notifications/{id}/ack`.
- (b) Paths enumerated and read/grepped: `routes_crisis.py` `ack_notification` (lines 340-366, the Step 7 site: actor → 404 → shape → token → `SENT` → activation-state); fan-out (241-268) and `deactivate_activation` (292-302); grep for `ERR_ACK_TOKEN_MISMATCH`/`ERR_NOTIFICATION_ALREADY_ACKED` — only `routes_crisis.py:347,350`; grep for `ERR_INVALID_STATE` in `routes_crisis.py` — deactivate (297), ack (354), attestation sign (432), revoke (454), all target-resource state checks; other activation-touching modules: `routes_registry.py:204-206` (process-retirement live-activation check), `routes_analysis.py:420` (plan-retirement live-activation check), `calc.py:501-506` (coverage read), `serializers.py:151` (view), `core.py:36-37` (stores) — none evaluate ack guards.
- (c) Wording adjustments: the new layer-10 entry is scoped with "at acknowledgement" so it does not misdescribe deactivation (allowed set includes `ACKNOWLEDGED`) or the layer-11 retirement guards (live set `ACTIVE`/`ALL_NOTIFIED`/`ACKNOWLEDGED`); the ordering clause references only "the three acknowledgement guards" rather than reordering §2.10's global layer list, leaving layers 1-9 and 11-15 and every other endpoint's precedence untouched.

## Step 9: Complete PRD — 2026-08-11T11:12:00.000Z

Step 9 complete. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1170_business_continuity_disaster_recovery/workspace/PRD_COMPLETED.md`.

**Size**: PRD_FINALIZED.md 440 lines / 83,255 chars → PRD_COMPLETED.md 445 lines / 88,993 chars (char-delta +5,738; 29 edit hunks, all inline — no new sections).

**Counts**: 25 ambiguity-pins, 5 mismatch-revisions.

**Mismatch revisions** (PRD said X, impl does Y — PRD revised to Y):
- §3.1 — revise — mismatch — "only an ACTIVE process can accept new analyses" recast: BIA/plan *creation* is open while the process is DRAFT or ACTIVE and refused (ERR_PROCESS_NOT_ACTIVE) only for SUSPENDED/RETIRED; ACTIVE is required only for submissions, exercises, activations — routes_analysis.py:36-41 (`_process_allows_new_children`) vs submit_bia:183
- §3.1 — revise — mismatch — blast-radius member order: replaced "ordered by discovery-edge created_at" with the actual order: BFS from the target, outgoing edges explored in ascending edge `created_at`, members in first-discovery order (the two orderings genuinely diverge when a deeper discovery edge is older than a shallower one) — calc.py:152-173
- §3.4 — revise — mismatch — "becomes assessable only after activation" recast: assessments may be drafted against a vendor in any standing; ACTIVE is required only at finalization — routes_vendor_site.py:162-192 (no status check at create) vs :248-250
- §3.6 — revise — mismatch — root_cause "(which may also be filled in later at verification time)" removed; verification/rejection record no narrative fields — routes_exercise.py:316-352 (verify/reject read no such payload)
- §3.8 — revise — mismatch — ack counter maintenance is silent: a non-completing acknowledgement leaves the activation's `version`/`updated_at` untouched notwithstanding §2.5; version increments only on the ALL_NOTIFIED→ACKNOWLEDGED auto-advance — routes_crisis.py:356-365

**Ambiguity pins** (PRD silent — pinned to impl):
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical program clock, never wall-clock — core.py:140-144
- §2.2 — insert — ambiguity — infrastructure errors: unrouted path → ERR_NOT_FOUND 404; unsupported method → ERR_METHOD_NOT_ALLOWED 405; server fault → ERR_INTERNAL 500 — app.py:34-47
- §2.3 — insert — ambiguity — pagination clamped not rejected (limit→[1,100], offset→≥0, unparsable→defaults); filters are exact case-sensitive equality; undeclared query params ignored — core.py:275-309
- §2.4 — revise — ambiguity — `current_utc` echoes the supplied `to_iso8601` string verbatim — routes_registry.py:44-49
- §2.9 — insert — ambiguity — nested id resolving under a different parent fails with the nested resource's own NOT_FOUND (e.g. section of another plan → ERR_SECTION_NOT_FOUND) — routes_analysis.py:479-483
- §2.10 layer 5 — revise — ambiguity — null counts as missing; non-object body treated as empty; undeclared fields ignored; presence before shape per field; wrong JSON type → ERR_VALIDATION; positivity domains pinned (seat counts ≥1; all hour quantities, ack_deadline_minutes, monetary amounts ≥0); cross-field rules run after all fields examined — core.py:201-268
- §2.10 — insert — ambiguity — layer-4/layer-5 interleave positionally: creation payloads examined in §3 field-naming order, each field's reference resolution applied when reached (vendor owner after name/category/rating; process owner after name/business_unit; reservation created_by after purpose/seats/window; node parent after tree_label/contact_name/role_title) — routes_vendor_site.py:46-53, routes_registry.py:99-104, routes_vendor_site.py:374-391, routes_crisis.py:94-110
- §3.2 — insert — ambiguity — every named field incl. `peak_period_flag` required at BIA creation; only peak months conditional — routes_analysis.py:99-104
- §3.2 — revise — ambiguity — decision literals pinned to `APPROVE`/`REJECT` — routes_analysis.py:196-197
- §3.3 — insert — ambiguity — "latest" BIA for the adoption pin defined (updated_at desc, created_at desc) — calc.py:57-64,84-89
- §3.5 — insert — ambiguity — reservation temporal guards evaluated capacity → same-process overlap → contract currency, first failure masks — routes_vendor_site.py:394-407
- §3.5 — insert — ambiguity — `probe_at` defaults to current program time; unparsable → ERR_VALIDATION — routes_vendor_site.py:343-349
- §3.6 — insert — ambiguity — failover disjointness considers all non-CANCELLED FAILOVER exercises of the process, excluding self at reschedule — routes_exercise.py:33-41
- §3.6 — insert — ambiguity — cascade-created validation run leaves `evidence_ref` empty — routes_exercise.py:195-197
- §3.6 — revise — ambiguity — finding-remediation gap copies the finding's `description` too — routes_exercise.py:297-299
- §3.7 — insert — ambiguity — run-created gap: severity HIGH, auto-generated description, due_date +90 days — calc.py:294-304
- §3.7 — revise — ambiguity — "twelve months" = twelve calendar months via month arithmetic with day clamped; exactly-12-months-old still CURRENT — calc.py:333-345, core.py:117-125
- §3.8 — insert — ambiguity — parent resolution errors pinned: nonexistent parent → ERR_NODE_NOT_FOUND; different tree_label → ERR_VALIDATION 400 — routes_crisis.py:105-110
- §3.8 — insert — ambiguity — root-uniqueness and sibling-order checks count inactive nodes; inactive parent doesn't block child creation; check order pinned (create: parent → root → sibling; update: scalar fields → parent → sibling → root → children → cycle) — routes_crisis.py:57-87,142-196
- §3.8 — insert — ambiguity — active nodes orphaned by an inactive ancestor still fan out, appended after tree order in creation order — calc.py:492-496
- §3.8 — revise — ambiguity — `ack_token` revealed in both list and detail reads — serializers.py:159-170
- §3.8 — insert — ambiguity — coverage field named `coverage_pct` — serializers.py:155
- §3.9 — revise — ambiguity — DRAFT readiness recomputed on every read, list or detail — serializers.py:173-176
- §3.9 — revise — ambiguity — snapshot_payload exact key set pinned (process_id, readiness_score, approved_plan_id, approved_plan_version_no, capability_states ordered by creation, open/overdue_gap_count, latest_completed_exercise_{id,result,scheduled_end}, captured_at) — calc.py:444-465
- §5 — insert — ambiguity — three catalogue rows added: ERR_NOT_FOUND 404, ERR_METHOD_NOT_ALLOWED 405, ERR_INTERNAL 500 — app.py:34-47

All other impl behaviors (112 routes, 16 state machines, 9 calculations, guard orderings, cascade side effects, version/updated_at rules incl. the run-supersede exception, filters, sub-collections, envelope shapes) were verified to already have verbatim anchors in PRD_FINALIZED.md.
