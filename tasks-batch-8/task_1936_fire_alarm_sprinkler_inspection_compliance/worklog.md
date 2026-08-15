# Worklog — task_1936_fire_alarm_sprinkler_inspection_compliance

## Step 1: Create Task Directory — 2026-08-15T01:50:00.000Z

Pre-created by pipeline launcher: tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/ and workspace/ (verified present at orchestrator start; no new index computed, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-15T02:16:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rules × 2 instances = 18
- `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 36 full instances + 8 `excluded_because` stubs

## Design summary (maxed difficulty per directive)

- **Profile**: compliance_audit + temporal_windowing; layers: optimistic concurrency, cascading side effects, rate/threshold triggers, scheduled actions; segregation-of-duties role model; compound state machines.
- **15 entities**: Contractor, Technician, LicenseRecord, Property, ProtectedSystem, Device (self-referential replacement), InspectionPlan (OCC-guarded), InspectionEvent, Deficiency (cyclic correction/rejection), Impairment (buffer-overlap semantics), MarshalReport (self-referential revision loop), BackflowTest (compounding late penalty), FirePumpTest (coordination-gated), FalseAlarmCase (rolling-window tiered fees), ModificationPermit (OCC-guarded, impairment cascade).
- **86 endpoints** including `/_clock/set_current_utc` (default 2026-08-01T00:00:00Z), 30 error codes, 20 ordered validations, 12 calculations, 2 OCC concurrency rules, 3 roles (FireMarshal opaque; ContractorAdmin/Technician entity-backed).
- **Difficulty highlights**: dual-variant calcs on two domains (plan-fee day-vs-month proration 45699/40000; provisional-vs-audited compliance score 840/842); combinatorial formulas in modes (b) round-per-month compounding (46305) and (a) marginal permit tiers (9750 vs 7500 floor); cyclic state machines on Deficiency and MarshalReport; 3-hop decommission cascade and 2-hop permit→impairment cascade; priority conflicts (state>safety, temporal sub-ordering); boundary checks (3rd-alarm fee 15000, empty-plan ERR_EMPTY_PLAN); cross-entity gates (event×system impairment, report×deficiency); two interval semantics (half-open+4h buffer vs closed-closed aggregate capacity-3); compensating invariants (deadline conservation across attest/reject, fee-pool conservation across assess/waive).

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    86
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     36
  Calls scanned (§1.8+§1.9):  564

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

All numeric asserts were pre-computed by executing the formulas (fee tiers, proration, compounding, late fees, score deductions); all `${var}` placeholders trace to `captures:`; OCC version fields always reference captures; no sibling task was inspected.

## Step 3: Copy Shared Files — 2026-08-15T02:16:30.000Z

Copied ./INSTRUCTION.md to tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T02:25:00.000Z

All three hard contracts now verify clean. Here is the final report.

## PRD Generated

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/workspace/PRD.md`

**Structure:**
- §1 Introduction (2 paragraphs, regulatory-relationship framing)
- §2 Global Specifications — 10 subsections: RBAC with per-role `identity` prose (FireMarshal opaque; ContractorAdmin entity-backed by Contractor; Technician entity-backed by Technician), the verbatim §2.2 envelope block, pagination, resource identity/common fields, the logical clock (startup default `2026-08-01T00:00:00Z`) and daily sweep, the 20-rule ordered validation pipeline, nested-path/cross-aggregate integrity (with the `ERR_SYSTEM_CATEGORY_MISMATCH` / `ERR_DEVICE_REPLACEMENT_MISMATCH` aliases), the two OCC rules, compliance scoring + posture derivation, and money/date/rounding conventions
- §3 Business Logic — 9 subsections (contractor/licensing; property/system/device inventory; annual plan and prorated fees; inspection event execution; deficiencies; impairments; marshal reports; specialty testing + false alarms; modification permits), with all state transitions, calculations, and error triggers scattered into narrative; zero HTTP paths or methods inside §3
- §4 Endpoint table — 76 endpoints, 4 columns only
- §5 Error catalogue — 30 entries, 2 columns only, no trigger conditions

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input/query_params/path_params: 81 required, 81 present, 0 missing
  (first pass found plan_id, plan_posture, property_id, technician_id missing — repaired in §3.1–§3.4; second pass clean)
Status: PASS
```

```
Rule coverage check:
- validations[] priority: 20 checked, 20 expressed as explicit ordered list in §2.6, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (plan create w/ expected_property_version, permit create w/ expected_system_version; both rejected ERR_STALE_VERSION/412; no race framing), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed (preconditions + error ids + side effects incl. cascades), 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise prose (frequency table, next-due with month-end clamping and inheritance, both fee-proration variants, late-fee cap/rates, false-alarm tiers + residential halving + habitual surcharge, permit marginal tiers with single final rounding, backflow 5% monthly round-per-month compounding, compliance score with all 10 deductions + audited variant, posture thresholds, 10-hour impairment rule, 12/4/1 plan counts, plan posture evaluation order), 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (incl. Property.version bump on plan create, ProtectedSystem.version bump on permit create, DRAFT-report deletion-from-workflow on contractor deactivation), 0 missing
- entities[].fields[] structured content: defaults, computed sources, nullability, and all enum sets reconstructible from prose, 0 missing
- sibling-branch symmetry: restore from OPEN/NOTIFIED, cite from APPLIED/ISSUED, waive from OPEN/ASSESSED, fulfill from SCHEDULED/IN_PROGRESS — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 500
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notes:**
- The scaffold defines no numeric values for the critical/noncritical correction windows (`CRITICAL_CORRECTION_DAYS` / `NONCRITICAL_CORRECTION_DAYS` appear in descriptions only); per the no-invention rule, the PRD refers to them symbolically as "the critical correction window" and "the noncritical correction window" measured in days from event completion.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, per the constraint.

## Step 5: Generate Unit Tests — 2026-08-15T03:05:00.000Z

Generation complete and fully verified. Summary:

## What was generated

**`test_helpers/`** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/test_helpers/`):
- `types.py` — 15 entity TypedDicts + 18 enums (all entities carry the 4 common fields)
- `api_client.py` — `ApiClient(GenericApiClient)` with ~70 methods, one per PRD endpoint row, all under `/fire-compliance`
- `api_errors.py` — all 29 catalogue ids plus the 12 PRD-named aliases (`ERR_DUPLICATE_LICENSE_NO`, `ERR_DEVICE_REPLACEMENT_MISMATCH`, open-item aliases, …), registered via `set_error_http_status_map`
- `assertions.py` — 15 entity assertions + date/timestamp parsing helpers
- `factories.py`, `constants.py` (fee bases, frequency table, license-class mapping, all thresholds), `test_users.py` (opaque FireMarshal constant + mandatory per-instance builders for entity-backed `ContractorAdmin`/`Technician`)
- `fixtures.py` — tiered composites: `setup_inspection_site`, `setup_published_plan`, `setup_scheduled_event`, `setup_completed_event`, `setup_invoiced_backflow_test`, `setup_issued_permit`, alarm helpers, OCC-threaded `create_plan` / `create_permit_for_system`; identity threaded via `make_*_headers(entity["id"])` throughout

**`test_suite/`** — `conftest.py` + 11 numbered test files, **72 tests**: 36 difficulty-queue (all 18 §1.8 instances × 2) + 36 corner-queue (all 36 non-stub §1.9 instances × 1). The 8 `excluded_because` stubs were not translated; all their difficulty-instance cross-references resolve.

## Key PRD-first adjudications
1. **Correction windows are never numerically pinned in the PRD** ("the critical correction window in days" / "the longer noncritical correction window" carry no values). Every instance that hard-coded deadline dates (e.g. `2026-09-02`, `2026-08-04`, fee 25000/600000) was translated to **capture `correction_deadline` from the API and derive expectations arithmetically** — the asserted rules (30-day cap → 600000, +30-day extension, byte-identical deadline conservation across reject, fee = days×5000/20000) remain exactly the design instances' claims, but stay true for any PRD-faithful window length. Clock advances are always monotonic (`max(deadline+1, …)`).
2. `compliance_score_provisional_vs_audited_diverge`: clock parked at `max(deadline)+1` so the three deficiencies are overdue for any window; the 840/842 divergence and non-persistence are asserted.
3. Alias-class errors asserted via `validate_error_is_one_of` + explicit status (PRD names both class and alias without committing to which string is emitted).
4. `version == 1` literal not asserted (PRD pins only "starts on creation and increments by one"); the increment-by-one rule is asserted instead.
5. No `skip`/`skipif`/`xfail` anywhere; no weakened status-only checks.

## Verification results
- `compileall` clean; all 11 test modules import; `pytest --collect-only` → **72 tests collected**
- Coverage audit: **PASS** — 54 distinct tags, every difficulty instance ≥2 tests, every non-stub corner instance ≥1, zero untagged/dual-tagged, zero stub translations
- Citation audit: **PASS** — every docstring's quoted PRD text has a ≥8-word substring literally present in `workspace/PRD.md`; every `error_id` asserted is named in PRD prose

## Step 6: Generate Implementation — 2026-08-15T03:30:00.000Z

The implementation is complete and fully green. Final report:

## Implementation complete: task_1936 Fire Alarm & Sprinkler Inspection Compliance

**Result: 72/72 tests pass** under `prd-bench-local-run --isolation per-test-server`, verified in two consecutive full runs (91s and 89s).

### What was built — `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/workspace/implementation/`

Python + Flask, in-memory store, following the mandated layout:
- `start.sh` — executable, guarded `pip install` (no-op once flask present), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — blueprint registration, global request lock (cascades never interleave), envelope-shaped error handlers
- `db.py` — empty-at-boot store plus logical clock (startup default exactly `2026-08-01T00:00:00Z`, never falls back to wall-clock)
- `errors.py` — full 30-id error catalog; PRD alias names (`ERR_DUPLICATE_LICENSE_NO`, `ERR_OPEN_IMPAIRMENT_EXISTS`, `ERR_SYSTEM_CATEGORY_MISMATCH`, etc.) are carried on the wire by their canonical class ids
- `services/calc.py` — all 12 calculation rules with Decimal round-half-up at the spec-pinned points; `services/sweep.py` — the five-job daily sweep (license/permit expiry, plan lapse, late-fee accrual, impairment promotion) plus backflow monthly compounding
- `routes/` — all 70 endpoints from the §1.5 table

### Verified against the design-pinned literals
- Fee proration: provisional 45699 (139/365 day-based) vs final 40000 (4/12 month-based), provisional retained after publish
- Compliance score: provisional 840 persisted vs audited 842 (on-time bonus), posture PROBATION at 840, SUSPENDED at 880 with 3 overdue criticals, 925 after lapse, 980 after no-access
- Permit fee: 9750 marginal-straddle, 7500 minimum floor, doubled on cite
- Backflow compounding: 40000 → 44100 (2 months) → 46305 (3 months), rounding per step
- Deficiency cycle: deadline invariant across attest/reject (2026-09-02 conserved), 25000 after 5-day-late re-attest, 600000 cap at 30 days
- False alarms: tiers 0/0/15000, 75000 at sequence 7 (with habitual surcharge), 7500 residential half-rate, 364-day window exclusion, WAIVED excluded from sequencing
- Impairment buffer: adjacency (start == prior end) rejected, start == end+4h allowed; OUT_OF_SERVICE promotion after >10h gates event start with `ERR_SYSTEM_OUT_OF_SERVICE`
- Priority ordering: `ERR_INVALID_STATE` (5) beats `ERR_LICENSE_NOT_VALID` (7) on cancelled-event start
- OCC: plan create and permit create return 412 on stale version and bump the parent's version on success; decommission 3-hop cascade keeps `total_events_required` at 4 (cascade does not recompute device-derived totals, so the plan correctly does not auto-fulfill)
- Fresh-boot isolation confirmed: kill + relaunch via `start.sh` yields an empty store and the default clock; sweeps run only on `_clock/set_current_utc`

### Test-side fixes (3 unambiguous generation bugs, all PRD-aligned)
The initial run had 15 failures, all in test scaffolding, none in the implementation:
1. `test_helpers/fixtures.py` — `setup_inspection_site` indexed `devices[0]` unconditionally; 10 tests pass `device_count=0`. Now `"dev": devices[0] if devices else None`.
2. `test_helpers/fixtures.py` — `setup_issued_permit()` didn't accept the `legal_name` kwarg 3 tests pass. Now accepts `**site_kwargs` and forwards to `setup_inspection_site`.
3. `test_suite/test_05_event_execution_and_gates.py` + `fixtures.py` — `_expired_license_site` used `expires_on="2025-01-01"` with the default `issued_on="2026-01-01"`, an invalid pair the PRD requires rejecting (422 `ERR_INVALID_DATE_RANGE`); the design recipe used issued 2024-01-01. Added a `license_issued_on` helper parameter and set the test to the recipe's valid pair.

## Step 7: Run Tests and Iterate — 2026-08-15T03:45:00.000Z

The 8-round parallel sweep is fully clean: every one of the 72 tests has `status: "passed"` in all 8 rounds, with zero failures, zero errors, and zero skips. The exit condition is met.

## Summary

- **Iterations run:** 1 (the single 8-round parallel stability sweep).
- **Test results:** 72/72 passed in each of the 8 concurrent rounds (576 total test executions, all green; 0 failed, 0 errors, 0 skipped, 0 flaky).
- **Tests deleted:** none. No PRD-silence or unique-derivability violations surfaced because no test failed in any round, so the diagnostic protocol's STEP 1 deletion criteria were never triggered.
- **Fixes applied to `test_helpers/`:** none this round. (Step 6's generator had previously applied 3 fixes — `fixtures.py` `devices[0]` indexing, `setup_issued_permit` `**site_kwargs` forwarding, `_expired_license_site` license date pair — which this sweep confirmed are stable.)
- **Fixes applied to `implementation/`:** none this round. The existing implementation under `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/workspace/implementation/` (Flask app with `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `util.py`, `routes/`, `services/`, launched via `start.sh`) passed all 72 tests under per-test-server isolation across all 8 parallel rounds with no timing- or ordering-sensitive flakiness detected.

## Step 8: Finalize PRD — 2026-08-15T03:46:00.000Z

SKIPPED per the skip condition: Step 7 exited on its first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — zero iterations beyond the baseline. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md was produced.

## Step 9: Complete PRD — 2026-08-15T04:05:00.000Z

All 32 edits landed cleanly (29 diff hunks; two source lines each received two edits, and the §2.6 note is a 2-line insert). Final report:

## Summary

**Files** (both in `/home/ubuntu/github/CodingPRD/tasks/task_1936_fire_alarm_sprinkler_inspection_compliance/workspace/`):
- `PRD.md`: 393 lines, 58,793 bytes
- `PRD_COMPLETED.md`: 395 lines, 62,232 bytes
- Delta: +2 lines, +3,439 bytes (+3,386 chars)

**Counts**: 25 ambiguity-pins, 7 mismatch-revisions (32 changes total).

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl file:line):

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — implementation/response.py:66-88
- §2.3 — insert — ambiguity — `created_at` ties break by insertion order (earlier-created first) — implementation/response.py:94
- §2.4 — revise — ambiguity — `version` starts at 1 (was "starts on creation") — implementation/services/core.py:8-16
- §2.5 — revise — ambiguity — clock may be set to any instant, earlier or later; no monotonicity enforced — implementation/routes/clock.py:20, implementation/db.py:27-30
- §2.6 — insert — ambiguity — rules 14 (enum) and 18 (shape) fire where the body is parsed, at field-consumption point, not at list position; bodyless endpoints skip rule 18 — implementation/util.py:9-85, implementation/routes/permits.py:168-174
- §2.9 — revise — ambiguity — audited-score bonus window pinned: events completed on or after audit date − 90 days through the audit date inclusive — implementation/services/calc.py:481-488
- §3.1 — revise — ambiguity — `INACTIVE` technician barred only from event-lead assignment (`ERR_INVALID_STATE`); may still be named specialty-test tester (license validity still gates) — implementation/routes/events.py:59-60, implementation/routes/specialty_tests.py:56,174
- §3.2 — revise — mismatch — `certification_cycle_anchor` must fall in year 2000 (else `ERR_INVALID_REQUEST`) and is never consulted by the §3.3 fee formulas (was: "anchor the certification year for proration") — implementation/routes/systems.py:34-36, implementation/services/calc.py:220-256
- §3.2 — revise — mismatch — replacement device inherits the earlier of its own *current* `next_due_date` and the replaced device's `next_due_date` (was: "install-date-derived default") — implementation/routes/devices.py:139-141
- §3.2 — revise — ambiguity — archive cascade also cancels lapsed plans' still-`SCHEDULED` child events — implementation/routes/properties.py:90-97
- §3.2 — insert — ambiguity — `DECOMMISSIONED` system rejects device registration, impairment opening, backflow/pump test recording, and permit application with `ERR_INVALID_STATE` — implementation/routes/devices.py:49-50, impairments.py:65-66, specialty_tests.py:35-36, permits.py:43-44
- §3.3 — insert — ambiguity — plan-totals refresh touches only non-terminal plans; `FULFILLED`/`LAPSED` plans keep recorded counts — implementation/services/calc.py:157-161
- §3.3 — insert — ambiguity — provisional-fee day count clamped at zero when service start falls after Dec 31 of plan year — implementation/services/calc.py:233
- §3.3 — insert — ambiguity — final-fee month count is zero (fee zero) when service start falls after the plan year — implementation/services/calc.py:246-251
- §3.3 — revise — mismatch — every `LAPSED` plan feeds the 75-point deduction regardless of prior posture (was: only lapsing from `IN_PROGRESS`) — implementation/services/calc.py:446-448, implementation/routes/properties.py:91-93
- §3.4 — insert — ambiguity — scheduling rejected with `ERR_INVALID_STATE` when plan is `FULFILLED`/`LAPSED`, system not `IN_SERVICE`, or technician not `ACTIVE` — implementation/routes/events.py:55-60
- §3.4 — revise — ambiguity — covered devices = the system's `IN_SERVICE` devices at completion; an event covering none never counts as on-time — implementation/services/calc.py:128-131, implementation/routes/events.py:185-190
- §3.5 — insert — ambiguity — deficiency recording requires event `IN_PROGRESS` or `COMPLETED` (else `ERR_INVALID_STATE`); any `Technician` may record, not only the lead — implementation/routes/deficiencies.py:33,44-45
- §3.5 — revise — ambiguity — correction windows pinned: +1 day `CRITICAL`, +30 days `NONCRITICAL`; deadline assigned at recording if event already `COMPLETED`, else at completion — implementation/services/calc.py:45-46, implementation/routes/deficiencies.py:51-55
- §3.5 — insert — ambiguity — extending a deficiency with no assigned deadline still consumes the one allowance (`extension_used` → true) without moving any date — implementation/routes/deficiencies.py:187-193
- §3.6 — revise — mismatch — both impairment kinds store the client-supplied window; `discovered_at` is server-stamped (was: UNPLANNED `planned_start` "is set to the discovery time") — implementation/routes/impairments.py:59-60,44
- §3.6 — revise — mismatch — out-of-service measured from `planned_start` + 10h strictly (was: "remained in OPEN or NOTIFIED for strictly longer than ten hours") — implementation/services/calc.py:362-366
- §3.6 — revise — ambiguity — `notification_late` true only when notification is strictly after the deadline; at-deadline is on time — implementation/routes/impairments.py:129
- §3.7 — revise — ambiguity — `is_late` true only when submitted date is strictly after `report_due_date`; due-date submission is on time — implementation/routes/reports.py:106
- §3.7 — insert — ambiguity — per-jurisdiction portal receipt counter starts at 1 — implementation/routes/reports.py:135-137
- §3.8 — revise — ambiguity — backflow `device_id` must be a `BACKFLOW_ASSEMBLY` device of that system, else `ERR_CROSS_REFERENCE_MISMATCH` — implementation/routes/specialty_tests.py:62-63
- §3.8 — revise — ambiguity — pump tester needs an `ACTIVE` `PUMP` license with expiry strictly after the test date — implementation/routes/specialty_tests.py:174
- §3.8 — insert — ambiguity — non-chargeable case carries null `sequence_number` and assesses to a zero fee — implementation/routes/alarms.py:39,80-84
- §3.9 — revise — ambiguity — `project_valuation_cents` must be a non-negative integer; negative rejected with `ERR_INVALID_REQUEST` — implementation/routes/permits.py:37
- §3.9 — revise — ambiguity — auto-created UNPLANNED impairment's planned window runs from commencement instant to +8 hours — implementation/routes/permits.py:123-124
- §3.9 — revise — mismatch — permit close requires a `COMPLETED` event with `completed_at` strictly after `work_commenced_at` (dropped "passing"; events carry no pass/fail) — implementation/routes/permits.py:142-152
- §3.9 — revise — mismatch — closure re-seed is a practical no-op since the device-type→frequency mapping is a fixed table — implementation/routes/permits.py:154-156

**Verification**: diff hunks confined to the 29 intended locations (lines 78-257 of the source); no sections added or removed; all numbers cross-checked against `implementation/services/calc.py` constants and confirmed consistent with `test_helpers/constants.py` (auxiliary).

---

## Pipeline complete — 2026-08-15T04:05:00.000Z

All 9 steps finished. Final state: 72/72 tests passing across all 8 parallel stability-sweep rounds (results.1–8.json verified `passed == total` by orchestrator); PRD_COMPLETED.md present (395 lines). Step 8 skipped (clean first sweep).
