# Worklog — task_1561_referral_management_network_leakage

## Step 1: Create Task Directory — 2026-08-13T21:15:01.000Z

Task directory `tasks/task_1561_referral_management_network_leakage/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched. User directive: difficulty target is HARDER THAN EXPERT level.

## Step 2: Generate Scaffold — 2026-08-13T22:20:44.000Z

Scaffold generation complete for task_1561_referral_management_network_leakage. All three files written and lint-clean on the final run:

**Verdict block (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (785 calls scanned)

**Counts:**
- Entities: 13 (ReferringProvider, SpecialistProvider, InsurancePlan, Patient, NetworkParticipation, PriorAuthRule, Referral, AuthorizationRecord, Appointment, ConsultNote, LoopClosure, LeakageRecord, ProviderPeriodSnapshot)
- State machines: 8 — Referral (10-state branching with NEEDS_INFO and REOPENED cycles plus sweep expiry), ReferralAuthStatus (parallel cyclic dimension: AUTH_DENIED/EXPIRED → AUTH_PENDING loops), Appointment (diamond + compensating EXCUSED), SpecialistProvider, Patient (threshold posture), NetworkParticipation, InsurancePlan, PriorAuthRule
- Calculations: 11 (incl. dual-variant conversion_rate and no_show_risk_score; mode-(a) weighted specialty_match_ranking; mode-(b) per-line-then-sum estimated_leakage_exposure; SLA/grace/strike/utilization thresholds)
- Validations: 11 priority rows; Errors: 36
- Endpoints: 66 (incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z, aging-sweep ops-run checkpoint, analytics period close, live leakage-report)
- Roles: 5 — ReferringProvider (entity_backed), SpecialistProvider (entity_backed), ReferralCoordinator / ComplianceAuditor / NetworkAdmin (opaque); segregation-of-duties on loop closure (verifier ≠ scheduler user id)
- §1.8: 18 instances (2 per rule × 9 rules), all with structured recipes and pre-computed literal asserts (e.g., conversion 0.3333 vs 0.5000; exposure 53668 vs naive 53667; risk cap 112.5→100)
- §1.9: 56 instances (50 active + 6 excluded_because stubs), sections per claim-extraction guide

**Notable design decisions:**
- Flat topology with canonical FK annotations; every FK has a reverse-reachability GET (sub-resource or filtered list)
- True-race OCC on Referral.version for create-with-supersede booking and loop-closure writes (412 ERR_STALE_VERSION), checked after existence, before state
- Two distinct interval semantics for Rule 8: appointments use half-open datetimes + 15-min trailing buffer; participation windows use inclusive whole dates with next-day adjacency allowed
- Compensating invariants: patient strike ledger (no_show_strikes == count of NO_SHOW appointments) and specialist slot inventory (booked count == SCHEDULED+CONFIRMED count), each with forward/compensating action pairs
- Depth-3 cascade (no-show → strikes → patient posture → referral escalation) and depth-2 sweep cascade (expiry → LeakageRecord → provider watch flag at inclusive threshold 2)
- One inconsistency caught and fixed mid-authoring: the utilization-threshold corner instance's region math was contradictory; corrected so S1/S2 tie at 65 with created_at tie-break and match_score proving the inclusive 0.8 penalty

## Step 3: Copy Shared Files — 2026-08-13T22:21:16.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1561_referral_management_network_leakage/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T22:32:14.000Z

All structural checks pass: 66 endpoints in §4 matching the scaffold's 66 endpoint entries, 36 errors in §5 matching the error catalog, §2.2 byte-identical to the canonical block. The PRD is complete and all three hard contracts pass.

---

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1561_referral_management_network_leakage/workspace/PRD.md`

**PRD line count:** 289 lines

**Section list:**
- §1 Introduction (2 paragraphs — business-context/pain-point angle)
- §2 Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (all 5 roles, identity semantics for entity-backed vs opaque roles)
  - 2.2 API Response Structure (emitted byte-identical to canonical `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties and the Logical Clock (incl. the four `common_fields: false` exceptions and the `2026-08-01T00:00:00Z` startup default)
  - 2.5 Optimistic Concurrency Control (both OCC rules, no race-framing language)
  - 2.6 Precision, Rounding, and Time Arithmetic
  - 2.7 Validation Priority Order (all 11 priorities plus the temporal sub-order rule)
- §3 Business Logic & Workflows — 8 subsections organized by workflow timeline: 3.1 network roster, 3.2 patient risk posture, 3.3 intake/triage, 3.4 prior auth, 3.5 matching/assignment, 3.6 booking/visit lifecycle, 3.7 consult note/loop closure, 3.8 aging/leakage/analytics
- §4 Endpoint Definitions (66 rows, 4 columns)
- §5 Error Code Catalogue (36 rows, 2 columns)

**Coverage audit results (all PASS):**

```
Field coverage check (Contract 1):
- required set (entities[].fields + endpoint inputs/query/path params + common fields): 96 required, 96 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority ordering: 11 priorities + temporal sub-order, all expressed explicitly
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + expected_referral_version + ERR_STALE_VERSION/412 all named)
- state_machines[].transitions: all Referral/ReferralAuthStatus/Appointment/SpecialistProvider/Patient/NetworkParticipation/InsurancePlan/PriorAuthRule transitions expressed, including 6 cancel and 4 expiry sibling branches
- calculations[]: all 11 (sla_and_aging, auth_validity_window, specialty_match_ranking, panel_utilization, no_show_risk_score, strike_threshold_posture, conversion_rate, leakage_rate, estimated_leakage_exposure, provider_watch_flag, period_close_aggregation) expressed in precise prose with constants embedded
- validations[] conditions: all 36 error ids matchable to trigger prose in §2/§3
- endpoints[].side_effects: booking supersede cascade, no-show 3-link cascade, excuse reversal, expiry cascade, conditional leakage on cancel, auth CONSUMED on complete — all expressed
- entities[].fields[] structured content: defaults, initial values, computed-field semantics all reconstructible
- sibling-branch symmetry: PREFERRED/STANDARD scoring, urgency ladder, VERIFIED_CLOSED/REOPENED, OBTAINED/DENIED, cancel/expiry sibling groups — equal density
- 81/81 programmatic spot checks pass
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 459
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 byte-identical to canonical source; all 55 enum/state values present as exact strings; all 5 role names present; all 36 error ids present in §2/§3 narrative; §4 has exactly 4 columns × 66 endpoints; §5 has exactly 2 columns × 36 errors.

**Ambiguity-resolution decisions made:**
1. **`common_fields: false` on `ProviderPeriodSnapshot`** — the scaffold omits `common_fields` for this entity (unlike the explicit `false` on ConsultNote/LoopClosure/LeakageRecord). I treated it as a frozen snapshot row without `updated_at`/`version` (consistent with "frozen at close" semantics) and said so explicitly in §2.4.
2. **§2.7 temporal sub-order** — scaffold note says "window-shape errors before overlap errors before threshold/grace errors"; rendered verbatim as prose to make the sub-ordering explicit per Contract 2 category 1.
3. **`no_show_risk_forward` granularity** — scaffold precision note says "forward variant in 0.5 steps (12.5 granularity)"; translated as "moves in half-point steps of 12.5 granularity in practice" to preserve both numbers without pseudocode.
4. **Scaffold `age_days` formula `floor((now - created_at) / 86400)`** — translated as "floor of the elapsed seconds divided by 86,400 ... evaluated fresh at read time in UTC" (spelled out the seconds-per-day constant rather than copying the numeric expression).
5. **First-pass Contract 1 misses repaired:** added `referral_id` (AuthorizationRecord creation in §3.4, LoopClosure creation in §3.7), `appointment_id` (consult-note stamping in §3.7), and the literal `CANCELLED` state token (supersede cascade in §3.6). Second pass confirmed 0 missing.
6. **Audit-tooling note:** the first audit script falsely reported 91 missing fields because fenced code blocks (```` ```json ````) misaligned naive backtick pairing; stripping fences before token extraction fixed the audit (the PRD itself was fine).

## Step 5: Generate Unit Tests — 2026-08-13T23:22:01.000Z

Generation complete. All audits pass.

## Summary

**Test counts**
- **Queue A (Difficulty)**: 36 tests — all 18 instances covered with exactly 2 tests each (≥2 target met).
- **Queue B (Corner)**: 49 tests — 49 of 50 non-stub instances covered with ≥1 test each. The 6 `excluded_because:` stubs were not translated (all cross-references verified to resolve to real difficulty instances).
- **Total**: 85 tests, every docstring carrying exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag, plus verbatim PRD citations (a script confirmed a ≥8-word substring of every citation literally greps against PRD.md — 0 failures).

**Skipped instances (1)**
- `Corner/endpoints/referral_list_filter_combination` — **no PRD coverage**. PRD §2.3 names only `limit`/`offset` as query parameters; the §4 endpoint table never documents `status`/`specialty` filters for GET /referrals, so filtered-list outcomes are not uniquely derivable for a PRD-only reader.

**Partial translations (1)**
- `Corner/calculations/live_report_basis_selection_and_default` — emitted with the explicit `basis=INTAKE` (0.5000) and `basis=SCHEDULED` (1.0000) assertions only. The "omitted basis defaults to INTAKE" assertion was omitted under the `default-value` silence pattern (PRD says "optional" without naming the server-side default).

**Design decisions**
- Timestamp assertions compare parsed instants, not strings — PRD §2.4 requires three fractional digits on `created_at` while design YAML literals write `...T00:00:00Z`; instant comparison is the only form both PRD readers satisfy.
- Aging-sweep and period-close response bodies are asserted only for 2xx status; their JSON key names (`expired_count`, `snapshot_count`, etc.) are not named in PRD prose, so the corresponding design assertions were re-targeted to PRD-derivable entity reads (referral status, provider counters, leakage-record lists, snapshot list).

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1561_referral_management_network_leakage/`)
- `test_helpers/`: `types.py`, `api_client.py` (55 endpoint methods), `api_errors.py` (36 errors, registered with framework), `assertions.py` (13 entity assertions + ledger invariant checkers + instant/rate comparators), `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + `make_referring_provider_headers`/`make_specialist_provider_headers` entity-backed builders), `fixtures.py` (network bootstrap, referral lifecycle tiers through CLOSED, accumulation helpers), `__init__.py`.
- `test_suite/`: `conftest.py` + `test_01_referral_intake.py` (10), `test_02_network_roster.py` (5), `test_03_triage_cycle.py` (6), `test_04_prior_auth.py` (4), `test_05_matching.py` (7), `test_06_booking.py` (12), `test_07_visit_lifecycle.py` (6), `test_08_no_show_strikes.py` (11), `test_09_loop_closure.py` (6), `test_10_aging_leakage.py` (6), `test_11_analytics.py` (6), `test_12_access_and_envelope.py` (6). ~4,300 lines total; all modules compile and import cleanly.

**Untranslatable instances**: none beyond the one skip noted above.

## Step 6: Generate Implementation — 2026-08-13T23:22:34.000Z

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1561_referral_management_network_leakage/workspace/implementation/`)

- `start.sh` — guarded pip install (no-op once flask present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — flask>=3.0
- `app.py` — all 48 endpoints from the scaffold endpoint table
- `db.py` — in-memory store (plain dicts keyed by id), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, id/seq minting. **Nothing seeded at startup**
- `errors.py` — ApiError carrying scaffold error_id + HTTP status
- `response.py` — exact envelope: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`; list meta adds `limit/offset/total_count/has_more`; error body is `{error_id, message}`; timestamps ISO-8601 UTC with 3 fractional digits
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (401) and per-endpoint role gating (403)
- `helpers.py` — constants, shape validators, pagination (limit 1–100 default 10, offset default 0), derived fields, serializers, leakage-record creation

## Coverage highlights

- **All 13 entities** with exact field sets; ConsultNote/LoopClosure/LeakageRecord/ProviderPeriodSnapshot correctly omit `updated_at`/`version`
- **Validation priority order per PRD §2.7** (auth → role → ownership → shape → existence → OCC → state → business-safety → specialty/target → uniqueness → temporal, with window-shape before overlap before grace)
- **State machines**: full Referral lifecycle incl. request-info/resubmit/reject/accept/cancel/expire, parallel auth dimension (NOT_EVALUATED → … → AUTH_EXPIRED cycles), Appointment (confirm/complete/no-show/excuse/cancel/supersede), provider suspend/reactivate, plan/rule/participation retirement
- **OCC** `expected_referral_version` on booking and loop-closure (412, checked after existence, before state)
- **Calculations**: SLA days {2,7,30} with inclusive sweep boundary; match ranking (50 base, PREFERRED+25/STANDARD+10, exact-rational 0.8 utilization penalty inclusive, urgency bonus, case-sensitive region bonus, clamp [0,100], score-DESC/created_at-ASC tie-break, 422 empty pool); half-open [start, end+15m) overlap with adjacency allowed; 15-min no-show grace inclusive; 24h overdue risk (12.5-granularity forward score); strike limit 3 with escalation-flag cascade and excuse reversal; per-line round-half-up leakage cents (round-then-sum pinned order); 4dp round-half-up conversion/leakage rates with 0.0000 zero-denominator rule; watch flag at >= 2 never clearing; period close with `[start, end)` window, provider created_at-ASC order, and all three guard errors
- **RBAC + ownership**: entity-backed provider/specialist scoping (403 on foreign resources), SoD barring the scheduling user from verifying closure (403)

## Boot verification

`bash start.sh` was launched fresh on multiple test ports; each boot confirmed: empty store (`total_count: 0`), clock at the 2026-08-01 default, 401 without headers. Full happy path exercised (create → accept → auto-match score 90 → OCC booking → confirm → clock advance → complete → consult note → loop-closure → CLOSED), plus edge paths: supersede, OON booking leakage (27000 = 18000×1.5), cancel-leakage + watch flag at 2, aging sweep expiring 8 referrals with EXPIRED_UNRESOLVED records, auth expiry at inclusive boundary, REOPENED→second note (sequence 2)→VERIFIED_CLOSED, period close idempotency errors, utilization penalty at exactly 4/5, and all overlap/grace/complete boundaries at ±1 second. All passed. (Two mid-test anomalies were my shell test bugs — port reuse and bad slot arithmetic — not implementation defects; both retested clean.)

**Orchestrator note:** implementation summary says "48 endpoints from the scaffold endpoint table" while scaffold worklog and PRD §4 report 66 endpoint rows — possible counting-convention difference (route handlers vs table rows) or a coverage gap; Step 7's full-suite run will surface any genuinely missing endpoints as failures.

## Step 7: Run Tests and Iterate — 2026-08-13T23:37:28.000Z

All done. Final sweep is fully green.

## Summary

- **Iterations run:** 3 (each = 8 parallel rounds, 85 tests/round).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/` (2 — both plain missing-import bugs, not PRD-coverage issues):**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1561_referral_management_network_leakage/test_suite/test_02_network_roster.py` — added `create_referral_payload` to the `test_helpers` import list; `test_suspended_provider_cannot_create_referral` used it at lines 81/88 and died with `NameError` in all 8 rounds of sweep 1.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1561_referral_management_network_leakage/test_suite/test_10_aging_leakage.py` — added `validate_paginated` to the import list; `test_snapshot_exposure_sums_rounded_lines` used it at line 183 and died with `NameError` in all 8 rounds of sweep 1.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout.

- **Flakiness investigation (sweep 2, round 5):** `test_cancel_cascades_appointment_and_no_leakage_for_declined` failed once with `requests.exceptions.ConnectionError: Connection reset by peer`. Server log `/tmp/prd_bench_server_56177.log` showed the Flask process received an external **SIGTERM** ("Terminated") mid-test at 23:28:24 with zero tracebacks; the runner itself only ever sends SIGKILL (its kills appear as "Killed"). The SIGTERM landed in the narrow window between the fixture's 6th bootstrap request and the referral POST, resetting the keep-alive connection. The same test passed in the other 7 rounds of sweep 2 and all 8 rounds of sweep 3. This is host-level cross-pipeline interference (the port registry showed ~20 concurrent holders from other pipelines), not a defect in the test artifacts or implementation, so no task-side change was made for it.

- **Final state (sweep 3):** all 8 rounds `passed == total == 85`, zero failures. Exit criterion met.

## Step 8: Finalize PRD — 2026-08-13T23:39:06.000Z

Files are identical, as expected.

## Report

**Outcome:** `PRD_FINALIZED.md` is byte-identical to `PRD.md` (288 lines, 0% delta). No edits were made.

**Reasoning:**

The `<step_7_diff>` for this task lists exactly four categories of items, and none of them reveal PRD silence or PRD/impl mismatch:

1. **Tests deleted: none.**
2. **test_helpers fixes: none.**
3. **test_suite fixes: 2** — both are pure missing-import mechanical bugs:
   - `test_02_network_roster.py`: added `create_referral_payload` to imports. Verified the helper is defined at `test_helpers/factories.py:71` and exported from `test_helpers/__init__.py`. The test was *using* the helper before importing it — a Python `NameError`, not a PRD ambiguity.
   - `test_10_aging_leakage.py`: added `validate_paginated` to imports. Verified the helper is exported from `test_helpers/__init__.py:4`. Again a `NameError`, not a PRD ambiguity.
4. **implementation fixes: none — the implementation was PRD-faithful throughout.** This is the load-bearing statement: since Step 7's edits scope is bounded to items in the diff, and the diff contains zero implementation changes and zero PRD-driven test adjustments, there is no concrete behavioral choice made by the implementation that PRD failed to pin.

The flaky `ConnectionError` in sweep 2 round 5 is explicitly attributed to host-level SIGTERM interference, not to any artifact — no PRD implication.

**Per-edit pre-edit search log:** No edits were committed, so no (a)/(b)/(c) entries are required. The mandatory pre-edit search triggered zero times.

**Files:**
- `workspace/PRD.md` — 288 lines (unchanged)
- `workspace/PRD_FINALIZED.md` — 288 lines (byte-identical copy; 0.0% delta)

**Line-count / %-delta summary:**
- PRD.md: 288 lines
- PRD_FINALIZED.md: 288 lines
- Delta: 0 lines, 0.0%

This is the "legitimately identical" outcome the prompt anticipates: the only Step 7 activity was repairing two import lists in test files, which says nothing about the PRD's specificity. A fresh implementer reading PRD_FINALIZED.md (== PRD.md) already has all the constraints the implementation actually embodies, as evidenced by sweep 3's 8/8 rounds at 85/85 passing with zero impl fixes.

## Step 9: Complete PRD — 2026-08-13T23:52:57.000Z

All edits applied cleanly. The diff confirms 17 paragraphs changed (some edits landed in the same §3.8 paragraph), all in-paragraph (line count unchanged at 288), character count 48,146 → 51,333 (+3,187). The work is confined to `workspace/PRD_COMPLETED.md` within task_1561.

## Summary

**Source:** `workspace/PRD_FINALIZED.md` (identical to PRD.md) → copied to `PRD_COMPLETED.md` and edited in place.
**Line counts:** 288 → 288 (all changes are inline in-paragraph edits; no new sections/paragraphs). **Char delta:** +3,187 (48,146 → 51,333).
**Counts:** 24 ambiguity-pins, 1 mismatch-revision (25 logical changes across 17 paragraphs).

Changes (impl paths relative to `.../workspace/implementation/`):

- §2.1 — insert — ambiguity — ReferringProvider scoping on `GET /analytics/snapshots`: result implicitly restricted to own snapshots; explicit `referring_provider_id` param naming another provider fails `ERR_OWNERSHIP_VIOLATION` — app.py:1351-1356
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit` (1–100) / negative `offset` fail `ERR_INVALID_REQUEST` (400) — helpers.py:161-181
- §2.3 — insert — ambiguity — `created_at` ties break in insertion order (earliest-created first, via internal seq) — helpers.py:184-185
- §2.3 — insert — ambiguity — list endpoints accept optional equality-filter query params on resource fields; unknown params ignored; date filters (`period_start`/`period_end`) parse `YYYY-MM-DD` and match nothing when unparseable; `total_count` reflects the filtered set — app.py:73-79, 614-618, 1352-1368 et al.
- §2.3 — insert — ambiguity — `GET /referrals` `leaked` param accepts exactly `true`/`false`, else `ERR_INVALID_REQUEST` — app.py:619-626
- §2.7 — revise — ambiguity — placed `ERR_NO_ACTIVE_PARTICIPATION` (409) in priority 10 (it was missing from the priority catalogue), matching booking-gate order — app.py:918-927
- §3.1 — insert — ambiguity — `weekly_capacity` < 1 fails `ERR_INVALID_REQUEST` — app.py:205-206
- §3.1 — insert — ambiguity — non-positive `payer_mix_factor` fails `ERR_INVALID_REQUEST` — app.py:370-372
- §3.1 — insert — ambiguity — plan retire requires current `ACTIVE`, else `ERR_INVALID_STATE` — app.py:410-411
- §3.1 — insert — ambiguity — participation terminate requires current `ACTIVE`, else `ERR_INVALID_STATE` — app.py:482-483
- §3.1 — insert — ambiguity — `auth_validity_days` < 1 fails `ERR_INVALID_REQUEST` — app.py:498-499
- §3.1 — insert — ambiguity — prior-auth-rule retire requires current `ACTIVE`, else `ERR_INVALID_STATE` — app.py:548-549
- §3.3 — insert — ambiguity — request-info carries a required `note` body field — app.py:657
- §3.3 — insert — ambiguity — reject carries a required `reason` body field, validated but not persisted — app.py:698
- §3.3 — insert — ambiguity — resubmit: supplied `insurance_plan_id` must exist (`ERR_PLAN_NOT_FOUND`); retired status not re-checked on resubmit — app.py:677-678
- §3.4 — insert — ambiguity — record-outcome `OBTAINED` validity-days fallback: ACTIVE rule for pair, else most recently created rule of any status, else 1-day default — app.py:845-851
- §3.5 — insert — ambiguity — auto-match candidates tied on score and `created_at` tie-break in insertion order — app.py:753
- §3.5 — revise — ambiguity — manual assignment: all three consistency failures (not ACTIVE, not accepting, wrong specialty) fail `ERR_SPECIALTY_MISMATCH` — app.py:770-773
- §3.6 — insert — ambiguity — overlap scan excludes same-referral appointments (they are superseded by the booking) — app.py:937-940
- §3.6 — revise — ambiguity — window-shape check pinned as evaluated after the participation gate and before the overlap scan — app.py:928-944
- §3.6 — insert — mismatch — escalation-flag set/clear side effects do not bump the referral's `version`/`updated_at` (exception to §2.4's every-mutation rule) — app.py:1118-1125 (no `bump`)
- §3.8 — insert — ambiguity — aging sweep responds HTTP 200 with fields `expired_referral_ids`, `expired_count`, `expired_auth_record_ids` — app.py:1094-1098
- §3.8 — insert — ambiguity — live leakage-report `basis` is exactly `INTAKE`/`SCHEDULED`, defaults to `INTAKE`, any other value fails `ERR_INVALID_REQUEST` — app.py:172-174
- §3.8 — insert — ambiguity — period-close bounds are ISO `YYYY-MM-DD` dates interpreted at midnight UTC — app.py:1305-1315
- §3.8 — insert — ambiguity — period close responds HTTP 201 carrying `snapshot_count` and `snapshot_ids` — app.py:1343

Everything else in the implementation (envelope shape, RBAC table, OCC guards, state machines, matching score formula, strike/risk math, leakage valuation and exposure summation, SLA windows, overlap/buffer geometry, error catalogue) was already uniquely pinned by the PRD and left untouched.
