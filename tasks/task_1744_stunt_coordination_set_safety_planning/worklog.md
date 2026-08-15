# Worklog — task_1744_stunt_coordination_set_safety_planning

## Step 1: Create Task Directory — 2026-08-14T12:48:00.000Z

Task directory `tasks/task_1744_stunt_coordination_set_safety_planning/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per instructions). Verified both exist and are empty.

## Step 3: Copy Shared Files — 2026-08-14T12:49:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1744_stunt_coordination_set_safety_planning/workspace/INSTRUCTION.md`. (Executed early, in parallel with Step 2 — no dependency on scaffold output.)

## Step 2: Generate Scaffold — 2026-08-14T14:09:00.000Z

All three scaffold artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1744_stunt_coordination_set_safety_planning/` and pass `scaffold_lint.py` with a clean verdict (910 calls scanned, zero violations).

## Counts

| Artifact | Count |
|---|---|
| Entities (§1.1) | 15 |
| State machines (§1.2) | 14 (13 entities; Production carries two parallel dimensions) |
| Concurrency/OCC rules (§1.2.1) | 3 |
| Calculations (§1.3) | 10 |
| Validation rows (§1.4) | 14 priority levels |
| Endpoints (§1.5) | 85 |
| Error codes (§1.6) | 65 |
| Roles (§1.7) | 6 (Performer is `entity_backed:StuntPerformer`; rest opaque) |
| §1.8 difficulty instances | 21 (all 9 rules; rules 2, 5, 6 carry 3 each) |
| §1.9 corner instances | 56 active + 6 `excluded_because` stubs across 10 sections |

## Notable design decisions

- **Topology**: flat (no URL nesting) per the skill's diversity guidance — all 15 entities are peers joined by FK fields, with filtered-list GETs satisfying FK reverse-reachability. Every money/risk literal in §1.8/§1.9 asserts was precomputed in Python (e.g., per-line-rounded rollup 267014 vs sum-then-round 267013; budget reserve available exactly 900000/90000).
- **Archetype blend**: compliance/audit primary + multi-party negotiation secondary (PayAdjustment is a cyclic PROPOSED↔COUNTERED negotiation with alternating-turn enforcement, a 6-round cap whose 7th counter is rejected *and* exhausts the negotiation to EXPIRED — this also keeps the enum closed).
- **Non-linear machines**: RiskAssessment revision loop (REJECTED→DRAFT), Production parallel dimensions (posture × insurance_status evolve independently), PayAdjustment counter rounds, and the EXECUTED→DESIGN_LOCKED reshoot/deficiency loop with `design_revision` pinning that invalidates prior safety meetings.
- **Two depth-3 transitive cascades** from different triggers: SERIOUS incident → STOPPED → SAFETY_HOLD → rehearsals CANCELLED; and FAILED inspection → QUARANTINED → SAFETY_HOLD → rehearsals CANCELLED (plus a third via safety-related abort → auto-incident).
- **Three OCC rules** (all true races per §1.2.1's serial filter): risk-assessment create (supersede semantics), execution create (version bumped by assessment approvals while sequence stays READY), and budget amend.
- **Segregation of duties** as the role model: approver ≠ assessor, signoff signer ≠ sequence designer, inspector ≠ equipment registrar — each with a dedicated §1.9 test.
- **Design fix discovered mid-generation**: the original lock threshold of 16 made CRITICAL-band sequences (screening ≥ 20 + hazard weight ≥ 2) mathematically un-lockable; the threshold was re-scaled to 26, giving clean boundary tests (PYRO S4L5 = 26 rejects; FIRE S4L5 = 25 locks).
- **Logical clock** endpoint (`POST /api/_clock/set_current_utc`) with the mandated 2026-08-01T00:00:00Z startup default drives all temporal boundaries: cert expiry equality (strict `>`), inspection staleness equality, permit windows, stoppage cooldown (86400s, `>=` passes).

## Step 4: Generate PRD — 2026-08-14T14:36:00.000Z

PRD generation complete. Final summary:

## Deliverable

**`/home/ubuntu/github/CodingPRD/tasks/task_1744_stunt_coordination_set_safety_planning/workspace/PRD.md`** — 410 lines. The withheld index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Section list

- **§1 Introduction** (2 paragraphs — business context + structural-safety/audit angle)
- **§2 Global Specifications** — 2.1 RBAC (six roles, per-role `identity` prose incl. entity-backed `Performer` and coordinator/author owner-restriction), 2.2 API Response Structure (**byte-verbatim** canonical block, verified by substring check), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, signoff sort exception), 2.4 Resource Identity & Common Fields (UUID/no prefix, ISO-8601 3-digit UTC, `version`; explicit Certification/Inspection exception: only `id`+`created_at`), 2.5 The Logical Clock (default 2026-08-01T00:00:00Z, strictly-forward, lazy derivations), 2.6 OCC (three rules), 2.7 Evaluation Order (all 14 validation tiers), 2.8 Safety Cascades & Version Propagation, 2.9 Monetary Precision (integer cents, round-half-up, per-line-before-sum), 2.10 Referential Integrity & Segregation of Duties
- **§3 Business Logic** — 3.1 Production/Budget/Insurance/Activation, 3.2 Sequence Design & Risk Assessment Cycle, 3.3 Performers/Certifications/Rehearsals, 3.4 Safety Meetings & Sign-Off, 3.5 Equipment/Inspections/Permits, 3.6 Readiness Gate & Safety Holds, 3.7 Hazard-Pay Negotiation & Committed Pay, 3.8 Takes/Incidents/Stoppages/Post-Stunt Review
- **§4 Endpoint Definitions** — 85-row table (4 columns), matching scaffold's 85 endpoints
- **§5 Error Code Catalogue** — 66-row table (2 columns): 65 `errors[]` entries plus `ERR_SERIOUS_INCIDENTS_OPEN` (409), which the scaffold's lift-stoppage precondition references but its `errors[]` table omits — reconciled at 409 to match its sibling stoppage-gate errors
- No audit footer; document ends at §5

## Coverage audit (scaffold → PRD passage)

| Scaffold rule group | PRD passage |
|---|---|
| `response_envelope`, pagination defaults | §2.2 (verbatim), §2.3 |
| 6 roles + identities | §2.1 (each role individually named; `Performer` entity-backed rule; opaque-role recording fields) |
| 3 `concurrency_rules` | §2.6 (write capability + `expected_sequence_version`/`expected_production_version` + `ERR_STALE_VERSION`/412 each; no race framing) |
| 14 state machines, all transitions/preconditions/side-effects | §3.1 (posture, insurance), §3.2 (sequence lock/cancel, assessment cycle incl. supersession + readiness invalidation), §3.3 (performer derivation, rehearsal complete/missed/cancel/void + I2), §3.4 (meeting + signoff machines, fan-out, REFUSED-completes nuance), §3.5 (equipment/inspection outcomes/permit), §3.6 (readiness, hold triggers, reverify, cancel cascade), §3.7 (negotiation turns, round-cap→`EXPIRED`, agree/withdraw/void + I1), §3.8 (execution, incident, stop/lift, review outcomes, wrap) |
| 10 calculations | §3.1 (insurance tiers 2/3/4% @ 100M/500M; cost roll-up with pinned per-line rounding + 133,507→267,014 example), §3.2 (risk_score screening/board variants, weights 6/5/4/4/4/3/2, credit −3, bands 1–5/6–11/12–19/20–25, lock threshold 26, quota 1/2/3/4 +1 special-equipment, medic rule), §3.3 (cert validity, overlap half-open + 1,800 s buffer), §3.5 (inspection currency, strict expiry), §3.7 (bump bounds floor/cap/surcharge 15,000/25,000, payout variants + 330,000 vs 380,000 example, budget authority 5-step order) |
| 14 validations with priority | §2.7 (explicit 14-tier ordered list) + trigger conditions scattered at workflows |
| 85 endpoints | §4 table (85 rows, verified) |
| 65 error ids (+1 reconciled) | all in §2/§3 prose (verified); §5 table (66 rows) |

## Hard Contract reports

```
Field coverage check:
- entities[].fields + endpoints input/query/path + named outputs: 105 required, 105 present, 0 missing
- all enum/state values: present (verified, including combined state-pair tokens)
Status: PASS

Rule coverage check:
- validations[] priority: 14 tiers expressed in ordered prose (§2.7), 0 missing
- concurrency_rules[]: 3 expressed (endpoint capability + occ field + ERR_STALE_VERSION/412), 0 missing
- state transitions: 14 machines fully expressed with error ids and side effects, 0 missing
- calculations[]: 10 expressed in precise prose (worked constants verified), 0 missing
- validations[] conditions: all matchable to error ids in §2/§3, 0 missing
- side effects / applies_to scopes: expressed (cascade link structure, posture-gate endpoint groups, readiness-gate order), 0 missing
- field structured content: defaults/nullability/initial values stated, 0 missing
- sibling-branch symmetry: inspection outcomes, review outcomes, signoff decisions, negotiation moves rendered at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 731
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One scaffold inconsistency handled: the `errors[]` condition text for `ERR_RISK_SCORE_ABOVE_THRESHOLD` says "board_score >= 16" while the calculations table (`LOCK_THRESHOLD: 26`) and the state-machine precondition both say 26; the PRD follows the calculations table and state machine (threshold 26, "at most 25 locks"), which is also consistent with the worked example (3×4 VEHICLE boards at 16 and must be lockable).

## Step 5: Generate Unit Tests — 2026-08-14T15:28:19.000Z

Task complete. Summary:

## Test generation for task_1744_stunt_coordination_set_safety_planning

### Counts
- **Queue A (Difficulty): 40 tests** across 20 of 21 instances (each ≥2 tests, satisfying the coverage target).
- **Queue B (Corner): 57 tests** covering all 56 non-stub instances (≥1 each; `cc_version_pinning_approval_invalidates_readiness` got 2). The 6 `excluded_because:` stubs were not translated; all 6 cross-references resolve to real difficulty instances.
- **Total: 97 tests**, all collected cleanly by pytest, zero skip/xfail markers.

### Instances skipped (1)
- **`Difficulty/cross_entity_state_dependency/xdep_execution_requires_permit_window`** — non-unique derivability. The instance's success path requires a PYRO sequence to pass mark-ready with a GRANTED PYROTECHNICS permit, but the PRD never states the hazard_class→permit_type mapping (§3.6 gate 5 says only "derived from its hazard_class together with the equipment_type"). A PRD-faithful implementer could map PYRO differently (e.g., FIRE_EFFECTS) and fail the setup. By contrast, the negative-case corner instance `err_permit_missing_at_readiness` (no permits at all → gate fails) IS robust to that ambiguity and was emitted.

### Recipe adaptations (PRD-internal consistency, assertions unchanged)
- `dv_pay_provisional_vs_final_settlement` test 2 reaches the second completed take via the reshoot loop (RESHOOT_REQUIRED → new revision-2 meeting → READY → take 2), because take creation requires READY and the first completion moves the sequence to EXECUTED. The asserted claim (provisional 270000 vs payable 320000) is verbatim-covered and derivable under both readings.
- `err_duplicate_take_number_rejected` exercises the PRD's own emphasized path ("even if the earlier take was aborted") so the sequence stays READY and tier-10 uniqueness is what fires.
- `cc_version_pinning_approval_invalidates_readiness` uses 1x3 (screening 3) for the second assessment — the instance's "S2L3 = LOW band" annotation contradicts the PRD's band table (6 is MEDIUM) and would fail at submit.
- `rbac_sod_self_inspection_rejected` activates the production first — PRD tier 5 requires ACTIVE for inspection recording, which would otherwise pre-empt the tier-11 SoD check.

### test_helpers/ (9 files)
`types.py` (15 entity TypedDicts — Certification/Inspection correctly omit `updated_at`/`version`, 20 enums), `api_client.py` (62 endpoint methods), `api_errors.py` (62 error ids + HTTP map registered with the framework), `assertions.py` (per-entity + invariant-I1 checker), `factories.py`, `constants.py` (PRD thresholds), `test_users.py` (6 roles + `make_performer_headers` for the entity-backed Performer role), `fixtures.py` (5 tiers incl. `setup_ready_sequence`, `setup_executed_sequence`, `reshoot_and_reready`, negotiation helpers), `__init__.py` barrel.

### test_suite/ (11 files)
`conftest.py` + `test_01_production_lifecycle.py` (12), `test_02_sequences_and_risk_assessments.py` (18), `test_03_performers_certifications.py` (5), `test_04_rehearsals.py` (13), `test_05_safety_meetings_signoffs.py` (6), `test_06_readiness_gates.py` (5), `test_07_equipment_permits.py` (5), `test_08_pay_negotiation.py` (17), `test_09_executions_incidents_reviews.py` (12), `test_10_security_rbac.py` (6).

### Stage 2 tag-audit result
Programmatic audit (AST docstring extraction + yaml cross-resolution + whitespace-normalized verbatim citation check against PRD.md): **0 untagged tests, 0 dual/malformed tags, 0 tags resolving to non-existent instances or stubs, 0 non-verbatim citations**; difficulty coverage 20/21 (the 1 gap is the sanctioned skip above); corner coverage 56/56 non-stub.

## Step 6: Generate Implementation — 2026-08-14T15:31:00.000Z

All checks complete. Final summary:

## Implementation complete — task_1744_stunt_coordination_set_safety_planning

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1744_stunt_coordination_set_safety_planning/workspace/implementation/`)
- `start.sh` — foreground launcher: guarded `pip install` (no-op when Flask present), `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, envelope-shaped error handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (dicts keyed by id) + logical clock (boots at exactly `2026-08-01T00:00:00Z`); no seeding
- `errors.py` — full 66-id error catalog
- `response.py` — envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (ISO-8601, 3 fractional digits), `response_type` (`object`/`array`/`error`), `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gate, structural payload validation (unknown/missing/invalid-enum/non-positive → `ERR_VALIDATION`, evaluated before auth per PRD §2.7), pagination parsing (default 10, clamped 1..100)
- `util.py` — UUID ids, ISO-8601 parsing/formatting, `Decimal` round-half-up
- `domain.py` — all calculations, readiness gates, cascades, serializers (explicit whitelists)
- `routes/` — 16 modules: `clock`, `productions`, `sequences`, `assessments`, `performers`, `certifications`, `rehearsals`, `meetings`, `signoffs`, `equipment`, `inspections`, `permits`, `adjustments`, `incidents`, `executions`, `reviews`

### Endpoints: 85/85 implemented (verified by route count)

### State machines: 14 implemented
Production `posture` (SETUP→ACTIVE→STOPPED→ACTIVE→WRAPPED) and parallel `insurance_status` (UNFILED→FILED→ACKNOWLEDGED); StuntSequence (DRAFT→DESIGN_LOCKED→READY⇄SAFETY_HOLD→EXECUTED→REVIEWED, reshoot/deficiency loops to DESIGN_LOCKED with `design_revision` bump, CANCELLED with compensation cascade); RiskAssessment (DRAFT→SUBMITTED→APPROVED/REJECTED→DRAFT revision loop, APPROVED→SUPERSEDED with re-pin + readiness invalidation); Performer (lazy QUALIFIED⇄REGISTERED via cert validity, SUSPENDED); Rehearsal (incl. VOIDED compensation); SafetyMeeting; DepartmentSignoff; EquipmentItem (quarantine/un-quarantine/retire); Permit; PayAdjustment (turn-based counter rounds, 6-round cap → EXPIRED on the failing attempt, AGREED→VOIDED compensation); Incident; StuntExecution (safety abort → auto-incident → stoppage chain); PostStuntReview.

### Calculations: 10 implemented
risk_score (screening + board variants, weights 6/5/4/4/4/3/2, mitigation −3, lock threshold 26 — worklog confirms the catalog's "16" is a typo), adjustment_payout (provisional 330000 vs 2-take payable 380000 verified), hazard_bump_bounds (union floor max(10%, 15000); caps 15/35/60/100% + 25000 PYRO_DEVICE/CRANE surcharge), production_cost_rollup (per-line round-then-sum), budget_authority_check (10% reserve on pre-agreement headroom, equality passes, HTTP 402), required_rehearsal_count (1/2/3/4 + 1 special equipment), inspection_currency (strict `>`, stale at exact elapse — verified), performer_certification_validity (strict `>` expiry — verified), overlap_checks (rehearsal half-open; meeting ±1800s buffer with exactly-1800s allowed — verified), insurance_endorsement_premium (2/3/4% tiers, inclusive-downward at 100M/500M — verified).

### Boot verification
`bash start.sh` verified on default port 10000 and custom `$PORT` (0.0.0.0 binding, fresh empty state per boot, clock default enforced via `ERR_CLOCK_NOT_FORWARD` on equality). Four smoke suites (~150 assertions) pass on fresh boots, covering envelope shape, auth/RBAC/owner checks, all three OCC rules (412), posture gating incl. `ERR_PRODUCTION_STOPPED` vs `ERR_PRODUCTION_NOT_ACTIVE`, both cascade topologies, medic-gate-before-meeting-gate ordering, signoff fan-out sets, SoD walls (approve/signoff/inspect), negotiation exhaustion, budget 402, and review-outcome loops.

### Judgment calls (spec gaps, resolved to the most defensible reading)
- Required-permit mapping is never tabulated in PRD/scaffold; used the name-aligned mapping: hazard PYRO→PYROTECHNICS, FIRE→FIRE_EFFECTS, WATER→WATER_WORK, AERIAL→AERIAL_WORK; equipment PYRO_DEVICE→PYROTECHNICS, CRANE→CRANE_OPERATION; HEIGHT/VEHICLE/FIGHT and other equipment types require no permit.
- Structural `ERR_VALIDATION` is evaluated before header auth (PRD §2.7's "structurally sound … then evaluated against the tiers" ordering).
- Out-of-range `limit`/`offset` are clamped to 1..100 / ≥0; non-numeric values → `ERR_VALIDATION`.

## Step 7: Run Tests and Iterate — 2026-08-14T15:36:37.000Z

All 8 rounds passed cleanly. The task is complete.

## Summary

- **Iterations run**: 1 (single 8-round parallel stability sweep — no fixes were needed)
- **Sweep result**: all 8 rounds `passed == total` (97/97 in every round, 0 failed, 0 errors, 0 skipped). No flakiness observed across the 8 concurrent per-test-server runs.
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**: none
- **Fixes applied to `test_suite/`**: none
- **Fixes applied to `implementation/`**: none

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1744_stunt_coordination_set_safety_planning/workspace/implementation/` already satisfies the full test suite (97 tests across production lifecycle, sequences/risk assessments, performers/certifications, rehearsals, safety meetings/signoffs, readiness gates, equipment/permits, pay negotiation, executions/incidents/reviews, and RBAC/SoD) with deterministic stability across all 8 parallel rounds.

Orchestrator verification: all 8 `results.{i}.json` files on disk confirm 97/97.

## Step 8: Finalize PRD — 2026-08-14T15:36:37.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-14T15:53:00.000Z

Done. All 18 edits applied cleanly (18 single-paragraph replacements, diff hunks at lines 48–243).

## Summary

**Files**: `/home/ubuntu/github/CodingPRD/tasks/task_1744_stunt_coordination_set_safety_planning/workspace/PRD.md` (410 lines, 70,698 chars) → `PRD_COMPLETED.md` (410 lines, 73,903 chars). Char delta: **+3,205**. No sections added; every change is an inline sentence/clause.

**Counts**: 17 ambiguity-pins, 1 mismatch-revision.

**Changes** (all paths under `/home/ubuntu/github/CodingPRD/tasks/task_1744_stunt_coordination_set_safety_planning/workspace/implementation/`):

- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the logical clock, not wall-clock — response.py:16-20
- §2.2 — insert — ambiguity — transport-level failures use the same error envelope: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — app.py:22-38
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_VALIDATION` (400); out-of-range integers clamped (`limit`→1..100, `offset`→≥0); default sort ties broken by creation order — middleware.py:181-199, domain.py:817-818
- §2.7 — insert — ambiguity — structural tier also covers non-JSON/non-object bodies (absent body = empty object) and empty strings for required reason fields — middleware.py:55-65, 77-80
- §2.7 tier 5 — insert — ambiguity — SETUP-or-ACTIVE-group operations attempted in any other posture (incl. STOPPED) yield `ERR_PRODUCTION_NOT_ACTIVE` — domain.py:195-202
- §3.1 — insert — ambiguity — `declared_exposure_cents` is a non-negative integer, zero permitted — routes/productions.py:143
- §3.1 — insert — ambiguity — activation evaluates posture before insurance; failing both → `ERR_PRODUCTION_NOT_ACTIVE` — routes/productions.py:190-195
- §3.2 — insert — ambiguity — `medic_standby_required` is null until design lock — routes/sequences.py:126
- §3.2 — insert — ambiguity — lock-design evaluates board-score threshold before the category-band match; failing both → `ERR_RISK_SCORE_ABOVE_THRESHOLD` — routes/sequences.py:186-195
- §3.2 — insert — ambiguity — revise treats omitted `mitigation_notes` as empty string, as at creation — routes/assessments.py:242,257
- §3.3 — insert — ambiguity — revoking an already-revoked certification succeeds idempotently — routes/certifications.py:106-124
- §3.6 gate 2 — **revise** — **mismatch** — medic standby is checked over *any* COMPLETED meeting pinned at the current `design_revision` (need not itself satisfy gate 3), replacing "the qualifying completed meeting — the one the next gate looks for" — domain.py:433-452
- §3.6 gate 5 — insert — ambiguity — tabulated the required-permit mapping: hazard PYRO→PYROTECHNICS, FIRE→FIRE_EFFECTS, WATER→WATER_WORK, AERIAL→AERIAL_WORK (HEIGHT/VEHICLE/FIGHT none); equipment PYRO_DEVICE→PYROTECHNICS, CRANE→CRANE_OPERATION (RIGGING/VEHICLE/HARNESS/AIRBAG none); sequences with no mapped requirement pass permit-free — domain.py:79-88, 310-321
- §3.7 — insert — ambiguity — `Performer`-role callers on counter/agree/withdraw must match the adjustment's `performer_id`, else `ERR_NOT_RESOURCE_OWNER` — routes/adjustments.py:65-68
- §3.7 — insert — ambiguity — counter evaluates state check, then turn check, then round cap; wrong-side counter at the cap → `ERR_NOT_YOUR_TURN` without exhaustion — routes/adjustments.py:205-216
- §3.7 — insert — ambiguity — agree likewise evaluates state before turn — routes/adjustments.py:246-251
- §3.8 — insert — ambiguity — abort-auto-created incident pins `production_id` (take's production), `occurred_at` (current logical time), `description` (= `abort_reason`), `reporter_user_id` (aborting coordinator) — routes/executions.py:243-252, routes/incidents.py:47-63
- §3.8 — insert — ambiguity — review close drives the sequence only while it still stands in `EXECUTED`; if it left `EXECUTED` (e.g., cancelled), the review closes and the sequence is unchanged — routes/reviews.py:147-167

**Verified, no change needed** (PRD already pins uniquely): structural `ERR_VALIDATION` before header auth (§2.7's "structurally sound requests are *then* evaluated" wording matches impl's validate-before-auth ordering in every route); all cascade shapes and version increments; tier ordering incl. OCC (tier 4) before posture (tier 5); posture-gate coverage (permit revoke, suspend/reinstate, incident investigate/close are gated in neither PRD nor impl); insurance tiering/rounding, budget-authority order, bump floor/cap formulas; rehearsal/meeting overlap and buffer math; signoff sort exception; OCC-guarded write set; §4 endpoint/role table — all match impl exactly.
