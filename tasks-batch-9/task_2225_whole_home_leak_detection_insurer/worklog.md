# Worklog — task_2225_whole_home_leak_detection_insurer

## Step 1: Create task directory — 2026-09-01T07:21:20.322Z

Created `tasks/task_2225_whole_home_leak_detection_insurer/` and `tasks/task_2225_whole_home_leak_detection_insurer/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T09:52:43.708Z

Note: first subagent attempt aborted with `max_output_tokens` (64000 cap) before writing any file; relaunched with an incremental chunked-write protocol, which succeeded.

All three scaffold files are complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2225_whole_home_leak_detection_insurer/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Scaffold surface**
- 13 entities (Homeowner, Property, Device, BaselineProfile, TelemetryReading, IrrigationWindow, AnomalyEvent, EmergencyContact, EscalationTicket, InsurancePolicy, CreditAttestation, ReimbursementClaim, DeviceTransfer); topology flat, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`.
- 10 state machines — Device carries three independent dimensions (`lifecycle_state`, `valve_state`, `monitor_mode`) plus BaselineProfile (cyclic COMPLETE→INVALIDATED→COLLECTING), AnomalyEvent, EscalationTicket, InsurancePolicy credit_state, CreditAttestation, ReimbursementClaim, DeviceTransfer.
- 3 `concurrency_rules` (valve-reopen-stale-device, transfer-create-stale-device, policy-create-stale-property).
- 10 calculation rules, 2 of them dual-variant (`premium_credit_award` PROVISIONAL/ANNUAL_TRUE_UP, `claim_payout_award` WARRANTY_FLAT/MITIGATED/UNMITIGATED); others: baseline learning, anomaly classification ladder, weighted severity score, auto-shutoff, uptime interval-merge coverage, false-positive tuning fixed point, escalation SLA, admissibility windows.
- 58 ordered validations (priorities 1–46), 44 endpoints (21 GET / 23 POST), 53 catalog errors, 6 roles.

**Difficulty design (depth)**: 9 rules × 2 = 18 instances, each pair carrying an explicit differentiation clause; all formula-derived asserts are hand-computed literals (e.g. baseline 60.0/6.00/0.12, uptime 95.00 → tier 0.05 → credit 3748, tuning ladder 0.12→0.14→0.17→0.20 then relearn + clawback to 0).

**Corner design (breadth)**: 71 instances across all 9 claim-extraction-guide sections — entities 12, state_machines 12, calculations 10, validations 8, endpoints 4, errors 14, rbac 4, complexity_layers 6, consistency_model 1. 53 are executable recipes; 18 are `excluded_because:` stubs, every one citing an existing §1.8 instance as `rule / name`.

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint` (923 setup/trigger calls scanned, 18 §1.8 + 53 §1.9 recipes). All 53 error ids are triggered by at least one instance; all 89 instance names unique; forbidden concurrency vocabulary removed. Fixed during this pass: wrong sweep path/payload, `stage` vs `ticket_state`, `vacation_ends_at`, CreditAttestation `status`, and eight mis-numbered validation-priority grounds refs.

## Step 3: Copy shared files — 2026-09-01T09:53:02.245Z

Copied `INSTRUCTION.md` → `tasks/task_2225_whole_home_leak_detection_insurer/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T10:05:32.579Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2225_whole_home_leak_detection_insurer/workspace/PRD.md` — **507 lines**, ending at §5 with no audit footer.

**Sections**

- §1 Introduction (3 paragraphs: product framing, credit economics, three design tensions)
- §2 Global Specifications — 2.1 RBAC · 2.2 API Response Structure (verbatim, byte-identical) · 2.3 Pagination · 2.4 Resource Identity, Audit Stamps and the Logical Clock · 2.5 Request Admission Order (all 46 priorities) · 2.6 Optimistic Concurrency Control · 2.7 Measurement Precision and Rounding · 2.8 Half-Open Intervals and Inclusive Boundaries · 2.9 Cascade Discipline · 2.10 Segregation of Duties
- §3 Business Logic — 3.1 Household Onboarding · 3.2 Device Provisioning, Pressure Hold Test, Baseline Learning (incl. firmware demotion) · 3.3 Telemetry Ingest, Classification, Severity · 3.4 Auto-Shutoff, Valve Override, Irrigation Exclusion · 3.5 Monitor Modes (Vacation/Snooze) · 3.6 Alert Escalation Ladder · 3.7 Resolution, Feedback, False-Positive Tuning · 3.8 Insurer Credit Program · 3.9 Reimbursement Claims · 3.10 Property Sale, Operational Sweep, Account Closure
- §4 Endpoint table (4 columns, 44 endpoints) · §5 Error table (2 columns, 53 codes)

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 143 required, 143 present, 0 missing
- endpoints[].request_body: 56 required, 56 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 46 checked, 46 expressed in prose (§2.5 normative ladder), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + occ_field + error_id + 412 all named), 0 missing
- state_machines[].transitions: 63 checked, 63 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (all 49 constants embedded in business context), 0 missing
- validations[] conditions: 46 checked, 46 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 44 checked, 44 expressed, 0 missing
- entities[].fields[] structured content: 143 checked, 143 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (ALERTED/SUPPRESSED fork; 3 FALSE_POSITIVE entries; 2 resolve entries; ticket ACK/EXPIRE pairs; 3 policy→TERMINATED; 3 device→DECOMMISSIONED; award/deny finalize; 3 payout variants; 3 invalidation causes), 9 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1014
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage audit — nothing omitted.** Two notes on judgment calls: (1) the scaffold's `monitor-mode` state-machine preconditions allow `LEARNING`, while validation priority 21 requires `ARMED` for `VACATION`/`SNOOZE`; I wrote the validation's `ERR_DEVICE_NOT_ARMED` gate as authoritative to avoid an ambiguous contract. (2) The telemetry side-effect list mentions `homeowner_notified_at` on `EscalationTicket`, which is not a declared field of that entity — I did not invent it, expressing the stage-1 notification through `notification_attempt_count` of 1 instead. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened.

## Step 6: Generate implementation — 2026-09-01T10:35:02.707Z

(Launched concurrently with Step 5; finished first.)

Implementation complete.

## Files created — `/home/ubuntu/github/CodingPRD/tasks/task_2225_whole_home_leak_detection_insurer/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | launcher (installs Flask only if missing, then `exec python3 app.py`) |
| `requirements.txt` | 1 | `flask>=2.2` |
| `app.py` | 73 | app factory, blueprint registration, `ApiError`/404/405/500 handlers in envelope form |
| `config.py` | 185 | every domain constant (Decimal/int) + all enum tuples |
| `errors.py` | 83 | all 55 error ids → HTTP status, `ApiError` |
| `clock.py` | 41 | logical clock, default `2026-08-01T00:00:00Z` |
| `util.py` | 243 | ISO-8601 (3-digit) format/parse, ROUND_HALF_UP helpers, body validators |
| `db.py` | 217 | 13 in-memory tables, insert/touch/version, ownership walks, `_seq` tie-break |
| `response.py` | 122 | `meta`/`response_type`/`data` envelope, pagination, query filters |
| `auth.py` | 121 | header auth, role gates, ownership + liveness checks |
| `serializers.py` | 339 | per-entity output incl. computed reads (`sample_count`, `mitigation_credited`, `avg_uptime_pct`, …) |
| `services.py` | 859 | all 10 calculations + every cascade (baseline, classification ladder, severity, auto-shutoff, uptime interval-merge, credit/true-up/clawback, payout variants, FP tuning, sweep, transfer accept, account closure) |
| `routes_accounts.py` | 283 | 7 GET + 5 POST |
| `routes_devices.py` | 444 | 4 GET + 6 POST |
| `routes_events.py` | 198 | 4 GET + 5 POST (incl. `/ops-sweeps`, `/_clock/set_current_utc`) |
| `routes_insurance.py` | 199 | 2 GET + 3 POST |
| `routes_claims.py` | 263 | 2 GET + 2 POST |
| `routes_transfers.py` | 191 | 2 GET + 2 POST |

Total 3,872 lines. **44 endpoints registered: 21 GET + 23 POST**, matching PRD §4 exactly. No startup seeding; every table starts empty.

## Boot confirmation
`PORT=18225 bash start.sh` in the background booted cleanly; `GET /anomaly-events` returned 200 with a full paginated envelope (`total_count: 0`, `api_request_timestamp: 2026-08-01T00:00:00.000Z` from the logical clock), and `POST /_clock/set_current_utc` returned `current_utc: 2026-09-01T00:00:00.000Z`. Process then killed. `python3 -m py_compile *.py` clean.

## Behaviour verified against PRD worked examples
- Uptime: 400-minute period with readings at 00:00/02:00/04:00/06:20 → `covered_minutes 380`, `uptime_pct 95.00`, `offline_gap_count 0`.
- Credit: premium 149900 at tier 0.05 books 3748/period; the second (year-closing) finalize sets `is_policy_year_close true` and `true_up_cents -1`, policy `credited_cents_total 7495`.
- Claims: loss 620000 on a mitigated burst → `MITIGATED`, deductible 0, payout 500000; full `BEGIN_REVIEW → REQUEST_INFO → SUPPLY_INFO → APPROVE → PAY` chain with SoD and cap checks.
- Escalation: `PENDING_HOMEOWNER` → (15 min, sweep) `PENDING_EMERGENCY_CONTACT` → (30 min, sweep) `EXPIRED/CONTACT_SLA_BREACH`.
- FP tuning: drip threshold 0.05 → 0.06 → 0.07 → 0.08, third FP invalidates the profile (`FALSE_POSITIVE_THRESHOLD`) and demotes the device to `LEARNING`.
- Transfer + account-closure cascades, snooze cooldown, and mode reverts via sweep all behave as specified.

One bug was found and fixed during verification: `services.finalize_attestation` counted the row being finalized in its own "prior finalized periods" set, firing the annual true-up one period early; it now excludes the current attestation.

## Step 5: Generate unit tests — 2026-09-01T11:55:14.731537113Z

(Launched concurrently with Step 6.)

All test infrastructure and test cases are complete and verified.

## Files created

`test_helpers/` — `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
`test_suite/` — `conftest.py` plus 18 test modules, **150 tests total**, all collecting cleanly (`pytest --collect-only` → 150 collected, 0 errors).

Per-file test counts:
| file | n | file | n |
|---|---|---|---|
| test_01_dual_variant_calc | 6 | test_10_entities | 14 |
| test_02_combinatorial_formula | 4 | test_11_state_machines | 14 |
| test_03_non_linear_state_machine | 5 | test_12_calculations | 10 |
| test_04_transitive_cascade | 6 | test_13_validations | 12 |
| test_05_priority_validation_conflict | 4 | test_14_endpoints | 11 |
| test_06_boundary_precision | 6 | test_15_errors | 17 |
| test_07_cross_entity_state_dependency | 6 | test_16_rbac | 9 |
| test_08_resource_temporal_overlap | 5 | test_17_complexity_layers | 11 |
| test_09_compensating_invariant | 6 | test_18_consistency_model | 4 |

## Coverage vs the design indices

- **Difficulty (queue A): 18 / 18 live instances translated** (48 tests, files 01–09).
- **Corner (queue B): 53 / 53 live instances translated** (102 tests, files 10–18). The 18 `excluded_because` stubs received nothing, as specified.
- **Nothing skipped.** Every live instance found verbatim PRD coverage that uniquely derived its outcome.

Static gates all pass: every one of the 314 docstring quotes is a verbatim PRD sentence (`bad 0`); all 150 tests carry exactly one `Design:` line; all 71 unique tags resolve to real instance `name:` values in the two yamls; no unused imports; no occurrence of "scaffold" in generated code.

## Design-index deviations (PRD won)

1. **Attestation finalize outcome** — design said `FINALIZED_AWARDED`; PRD arithmetic gives 160/240 = 66.67% < the 95.00 floor, so tests assert `FINALIZED_DENIED` + `UPTIME_BELOW_FLOOR` (test_15, test_16).
2. **Readings stamped past the clock** — several instances ingest at 06:10/06:20 with the clock at 06:05 (`ERR_READING_IN_FUTURE`); the clock is advanced first (test_16, test_17).
3. **verify-install body** — design used `static_pressure_psi`/`pressure_after_hold_psi`/`hold_duration_minutes`; PRD uses `installed_static_pressure_psi` + `pressure_drop_psi`.
4. **Attestation device resolution** — the rbac instance would have left two non-`DECOMMISSIONED` devices on one property (ambiguous resolution); the second device is now registered only after the finalize.
5. **Unverifiable retry claim** — one errors instance asserted a transfer succeeds after resolving the event; PRD leaves the valve `CLOSED`, so that hop was omitted rather than weakened.

## Cross-document discrepancy to flag

`SCAFFOLD_CORNER_DESIGN.yaml` states `ERR_SEGREGATION_OF_DUTIES` is **409**; PRD §2.5 step 40, §2.10 and the error table all say **403**. `api_errors.py` and test_16 assert 403.

## One infrastructure fix

`test_users.py` builders for the opaque roles (`make_program_admin_headers`, `make_gateway_headers`, `make_installer_tech_headers`, `make_insurer_analyst_headers`, `make_claims_adjuster_headers`) now default to their canonical ids — test_10/test_11 called them with no argument, which was breaking collection with a `TypeError`.

## Step 7: Run tests and iterate — 2026-09-01T12:36:25.463795276Z

All 8 parallel rounds now pass: **150/150 tests, 0 failures, 0 errors, 0 skips in every round** (identical results across rounds — no flakiness).

## Summary

**Iterations run:** 3 full 8-round parallel stability sweeps (108 failures → 6 failures → 0 failures).

**Tests deleted:** none. Every failure traced either to a fixture that built a PRD-inconsistent precondition or to an implementation check that contradicted a verbatim PRD sentence, so no assertion was dropped, skipped, xfailed, or downgraded.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_learning_device` verified the install at `FIXTURE_CLOCK_UTC` (06:05), so `learning_started_at` was 06:05 while `CANONICAL_LEARNING_READINGS` are stamped 00:00–00:40. PRD §3.2: "`sample_count` is the number of telemetry readings … whose `reading_at` falls at or after the profile's current `learning_started_at`", so none counted and the device never armed. Added an `install_clock=DEFAULT_CLOCK_UTC` step and restored the clock afterwards. This single fixture bug caused ~55 failures (TRIAGE HINT applied).
- `constants.py` — `TEST_DEFAULTS["SECOND_INSURER_CODE"]` was `SENTRY_MUTUAL` (13 chars), violating PRD §3.8's "an `insurer_code` of 2 to 12 uppercase characters", so admission step 4 fired instead of the step-9 `ERR_STALE_PROPERTY_VERSION` under test. Now `SENTRYMUTUAL`.

**Fixes applied to `test_suite/`** (all making the test more faithful to PRD, none weakening an assertion):
- `test_18_consistency_model.py` — `GET /escalation-tickets` was called with `InsurerAnalyst`; PRD §4 authorises "Homeowner, ProgramAdmin" only. Switched the acting identity to `ProgramAdmin`.
- `test_14_endpoints.py:315` — the second `BEGIN_REVIEW` was sent as `ProgramAdmin`; PRD §2.1 says a `ProgramAdmin` "cannot make the carrier's policy or claim-decision calls" and §4 lists ClaimsAdjuster/Homeowner/InsurerAnalyst for `POST /claims/{id}/decision`, so step 2 correctly returned `ERR_UNAUTHORIZED`. Switched to `ClaimsAdjuster`; the `ERR_CLAIM_NOT_REVIEWABLE` assertion is unchanged.
- `test_10_entities.py` — the inline second-household fixture verified the other device's install at 06:05 while its learning samples are stamped 01:00–01:40 (same clock-ordering bug as above). Added the clock steps so the sign-off precedes the samples.
- `test_07_cross_entity_state_dependency.py:140` — `sample_count == 3` contradicted PRD. §3.3 makes eligibility a biconditional ("a reading is baseline-eligible **exactly when** its frozen classification is `NONE`, its `reading_source` is `DEVICE`, and its `suppressed_by_irrigation` flag is false"), and the sibling test at :50 pins the TRANSFER_PENDING burst's `classification_at_ingest` to `NONE` from §3.3's "Classification itself runs only when the device's profile is `COMPLETE` and its `lifecycle_state` is `ARMED`". The reading is therefore eligible and the count is 4. Corrected to 4; the learned-value and `baseline_version` assertions (which show the COMPLETE profile does not recompute) are untouched.

**Fixes applied to `implementation/`:**
- `services.py` `recompute_baseline` — `baseline_version` was only incremented at the `COLLECTING → COMPLETE` hop; PRD §3.3 Step three increments it on every recompute. Also guarded so a non-eligible reading does not publish a snapshot.
- `services.py` `ingest_reading` — classification gate narrowed from `lifecycle_state in ("ARMED", "TRANSFER_PENDING")` to `== "ARMED"` per §3.3's "only when … `ARMED`". (§3.4's `DEVICE_NOT_ARMED` suppression clause is unreachable under that quantifier; the ladder never runs, so no event is minted.)
- `services.py` `invalidate_baseline` — `false_positive_count` was reset on every invalidation; PRD resets it only on the firmware and ownership-transfer paths (§3.2, §3.9), never on the `FALSE_POSITIVE_THRESHOLD` relearn (§3.6).
- `services.py` `finalize_attestation` — the annual true-up and `is_policy_year_close` only ran on the award path. PRD §3.7: the true-up "runs only on the finalize that brings the policy's `finalized_period_count` up to those two periods, at which point `is_policy_year_close` becomes true", and "A denied period contributes a tier of 0.00 to the annual sum". Hoisted the year-close computation so it runs on a denying finalize too, with the denial still booking no provisional credit.
- `util.py` `req_upper` — removed an invented `^[A-Z0-9]+$` character-class check that PRD never states (it rejected `AETNA_HOME`); the bound is only "2 to 12 uppercase characters". This unblocked ~40 tests.
- `routes_devices.py` telemetry ingest — dropped the account-liveness check: §2.5 step 7 applies "to every write endpoint that resolves a homeowner", and the gateway ingest resolves a device, so a deactivated household must surface `ERR_DEVICE_NOT_ACCEPTING_TELEMETRY` (step 14) instead.

Storage remains in-memory only, with no seeded or preloaded entity data. Run artifacts (`results.*.json`, `__pycache__`, two stray empty directories) have been removed.

## Step 8: Finalize PRD — 2026-09-01T12:48:19.300627475Z

All seven edits applied; PRD_FINALIZED.md differs from PRD.md in exactly 7 lines (all inline revisions, no new sections).

## Size
- PRD.md: 507 lines / 103,415 chars — PRD_FINALIZED.md: 507 lines / 105,821 chars → **line delta 0%, byte delta +2.33%**.

## Changes (one per bullet)
- **§2.5 step 7** — insert — telemetry ingest is exempt from the account-liveness check; a sample to a closed household's device surfaces step 14 `ERR_DEVICE_NOT_ACCEPTING_TELEMETRY` instead — `routes_devices.py:275-281`.
- **§3.3 step three** — insert — the recompute/publish step (and its `baseline_version` increment) runs only while the profile is `COLLECTING` **and** only when the just-stored reading is itself in the eligible set; otherwise nothing changes, and a cycle completing on its third eligible sample has incremented `baseline_version` three times — `services.py:69-105`.
- **§3.3 suppression list** — insert — the `TRANSFER_PENDING → DEVICE_NOT_ARMED` branch is unreachable, since a non-`ARMED` device never reaches the ladder — `services.py:381-391`, `services.py:268-270`.
- **§3.7 step four** — insert — the `FALSE_POSITIVE_THRESHOLD` invalidation does **not** zero `false_positive_count` (unlike firmware/transfer); the reopening reading clears it — `services.py:123-137`, `services.py:108-120`.
- **§3.8 policy creation** — revise — `insurer_code` is a length bound plus "no lowercase letter", not an `[A-Z]`-alphabet match (`AETNA_HOME` valid, `Aetna` → `ERR_INVALID_REQUEST`) — `util.py:236-240`, `routes_insurance.py:76`.
- **§3.8 denial paragraph** — insert — a denying finalize that brings `finalized_period_count` to two still sets `is_policy_year_close` and computes the annual true-up (tier 0.00 for that period), writing `true_up_cents` to attestation and policy and folding it into `credited_cents_total`, while booking no provisional credit — `services.py:559-583`.
- **§3.10 transfer freeze** — revise — during `TRANSFER_PENDING` telemetry is still ingested but classification does not run: `classification_at_ingest` freezes as `NONE` and no anomaly event is minted (the `DEVICE_NOT_ARMED` suppression is hypothetical) — `services.py:381-391`.

## Per-edit pre-edit search log
1. **§3.3 step three.** (a) Subject: baseline recompute / `baseline_version`. (b) Read `services.recompute_baseline` (sole caller `ingest_reading` step 3), `eligible_readings`, `reopen_profile_if_invalidated`, `false_positive_tuning` (+1 while `COMPLETE`), `serializers.sample_count`, `serializers.baseline_profile`. (c) Replaced an initial "COMPLETE or INVALIDATED" phrasing with "already `COMPLETE`" plus an explicit note that an invalidated profile has already re-entered `COLLECTING` earlier in the same ingest; scoped the "no change" claim to `baseline_version`/learned values/`completed_at` and deliberately did **not** restate the `LEARNING → ARMED` promotion (impl arms only from `LEARNING` while setting `baseline_ready` unconditionally).
2. **§3.10 transfer freeze.** (a) Subject: classification during `TRANSFER_PENDING`. (b) `ingest_reading` gate, `mint_event` suppression precedence, `routes_devices.ingest` accepted-posture list, `routes_transfers.initiate`. (c) Kept the `DEVICE_NOT_ARMED` suppression as counterfactual rather than deleting it, so §3.3's three-branch list stays coherent; omitted any claim about baseline eligibility of those readings (irrigation/`MANUAL_TEST` cases would falsify a universal).
3. **§3.3 suppression list.** (a) Subject: `mint_event` suppression branches. (b) All `mint_event` callsites (only `ingest_reading` under `ARMED`), snooze and duplicate-cooldown branches, `auto_shutoff`'s `SUPPRESSED` gate. (c) Said "unreachable in practice" rather than deleting the branch, keeping §3.4's "a burst arriving while snoozed" and the `SNOOZE_ACTIVE`/`DUPLICATE_WITHIN_COOLDOWN` branches untouched.
4. **§3.7 step four.** (a) Subject: `false_positive_count` lifecycle. (b) `invalidate_baseline` (all three reasons), `reopen_profile_if_invalidated`, `false_positive_tuning`, `deactivate_account` profile invalidation, `routes_devices.health_summary` exposure, §2.9 "fires identically" and §3.2/§3.10 reset sentences. (c) Scoped the sentence to the false-positive cause only, so the firmware/transfer resets and the closure path (which also leaves the count alone) remain correctly described; §2.9's chain never mentions the tally, so no conflict.
5. **§3.8 `insurer_code`.** (a) Subject: uppercase-string validation. (b) `util.req_upper` (only callsite `routes_insurance.create_policy:76`), plus neighbouring validators `req_string(lower=)`, `STATE_CODE`, `POSTAL_CODE`, free-form `policy_number`/`serial_number`. (c) Confined the wording to `insurer_code`; avoided any general statement about uppercase fields, since `state_code` really is `^[A-Z]{2}$`.
6. **§3.8 denial paragraph.** (a) Subject: year-close/true-up on a denying finalize. (b) `finalize_attestation` in full, `finalized_attestations` (excludes the current row), `serializers.finalized_period_count`/`avg_uptime_pct`, `clawback`, account-closure denial of `OPEN` attestations. (c) Added a new sentence instead of editing the denial's field list, so the list is not made to look exhaustive (impl also writes `device_snapshot_lifecycle_state` on denials where a device resolves — pre-existing, out of Step 7 scope); phrased the true-up as "computed there exactly as on an award" so the "runs only on the finalize that brings the count to two" quantifier and the closure path (which sets no year-close) stay true.
7. **§2.5 step 7.** (a) Subject: account-liveness applicability. (b) Grepped every `auth.alive*` callsite: contacts, property, irrigation window, device create, verify-install, valve, monitor-mode, firmware, feedback, resolve, acknowledge, policy create, attestation open, finalize, claim file, claim decision, transfer initiate (seller and buyer), transfer accept (buyer) — ingest is the only write without one; ops-sweep and clock resolve no homeowner. (c) Named telemetry ingest specifically rather than writing a general "device-resolving endpoints" carve-out, which would have wrongly excused `verify-install`, valve commands, mode changes, firmware and feedback/resolve — all of which do check liveness via `alive_device`.

## Step 9: Complete PRD — 2026-09-01T12:59:36.81697635Z

Patch complete: 36 lines revised in place, no lines added or removed, no new sections.

**Source vs output:** `PRD_FINALIZED.md` 507 lines / 105,821 chars → `PRD_COMPLETED.md` 507 lines / 115,042 chars (**+9,221 chars**, 36 lines touched, 39 in-paragraph inserts/revisions).

**Counts:** 31 ambiguity-pins, 8 mismatch-revisions.

### Changes

- §2.1 — insert — ambiguity — a device transfer resolves to *either* party, so seller or buyer passes the ownership check — `auth.py:90-95`
- §2.2 — revise — mismatch — `api_request_timestamp` is read from the logical clock, not wall time; `api_request_id` is `req_` + 20 uppercase alphanumerics — `response.py:20-28`
- §2.3 — insert — ambiguity — enum filters 400 on bad values, id filters yield empty pages, empty-string params read as omitted, top-level lists silently narrow for a `Homeowner` — `response.py:96-122`, `routes_events.py:60`, `routes_claims.py:72`, `routes_transfers.py:52`
- §2.5 step 21 — insert — ambiguity — `ERR_DEVICE_NOT_ARMED` also guards manual `CLOSE`, evaluated after step 23 — `routes_devices.py:334`
- §2.6 — insert — ambiguity — negative/non-integer expected-version is `ERR_INVALID_REQUEST`, not a 412 — `routes_devices.py:304`
- §3.1 — revise — mismatch — `email` is 1–320 chars, lowercase-only (no address grammar); duplicate → `ERR_INVALID_REQUEST` — `routes_accounts.py:151-156`
- §3.1 — insert — ambiguity — `city` bounded 1–120 chars — `routes_accounts.py:222`
- §3.2 — revise — mismatch — `firmware_version` validated only as a 1–40-char string, not as semver — `routes_devices.py:181`
- §3.2 — revise — mismatch — install verification's liveness gate is the homeowner account check, not `property_state` — `routes_devices.py:225`, `auth.py:114-121`
- §3.2 — insert — ambiguity — verify-install returns the updated device, not the new profile — `routes_devices.py:261`
- §3.2 — insert — ambiguity — arming bubble-up only fires from `LEARNING`; a `TRANSFER_PENDING` device gets `baseline_ready` true but keeps its state — `services.py:102-105`
- §3.2 — insert — ambiguity — identical `target_firmware_version` → `ERR_INVALID_REQUEST`, before liveness/transfer-lock — `routes_devices.py:432`
- §3.2 — insert — ambiguity — an armed push bumps device `version` twice (write + cascade) — `routes_devices.py:442-444`
- §3.3 — insert — ambiguity — advancing `last_reading_at` refreshes `updated_at` but does **not** bump device `version` — `services.py:376-377`
- §3.3 — revise — mismatch — a reading stored while `COLLECTING` is eligible only if also `DEVICE`-sourced and un-suppressed — `services.py:393-397`
- §3.3 — insert — ambiguity — suppression precedence is first-match (transfer, snooze, duplicate); cooldown scan ignores event state — `services.py:267-276`
- §3.3 — insert — ambiguity — a zero severity reference saturates that component at 1.0 when the value is above zero — `services.py:184-187`
- §3.4 — insert — ambiguity — manual `CLOSE` lifecycle failure is `ERR_DEVICE_NOT_ARMED`, checked after the transfer lock; `OPEN` has no lifecycle rule — `routes_devices.py:330-338`
- §3.5 — revise — mismatch — same-mode requests are legal, not `ERR_MODE_TRANSITION_FORBIDDEN` — `routes_devices.py:388-396`
- §3.7 — insert — ambiguity — a still-pending ticket blocks resolution with `ERR_EVENT_NOT_ACTIONABLE` — `routes_events.py:144-152`
- §3.7 — revise — mismatch — `FALSE_POSITIVE` feedback is accepted regardless of profile state; only the widening/relearn needs `COMPLETE` — `routes_events.py:112`, `services.py:628-642`
- §3.8 — insert — ambiguity — a property with no live device fails attestation opening with `ERR_BASELINE_NOT_COMPLETE` — `routes_insurance.py:139-145`
- §3.8 — insert — ambiguity — multi-device property scores the earliest-registered non-decommissioned device — `services.py:455-459`
- §3.8 — insert — ambiguity — health-summary window params are both-or-neither, end strictly after start, newest `OPEN` by `created_at`, all-zero fallback, profile-derived tail fields — `routes_devices.py:118-169`
- §3.8 — insert — ambiguity — true-up fires only when the count reaches *exactly* two; later periods leave `is_policy_year_close` false — `services.py:566`
- §3.8 — revise — mismatch — denial precedence is `NO_ENROLLED_DEVICE` → `DEVICE_NOT_ARMED` → `UPTIME_BELOW_FLOOR`, and denials also write `device_snapshot_lifecycle_state` — `services.py:535-544`
- §3.8 — revise — mismatch — clawback tie-break favours the *most recently created* awarded period — `services.py:496`
- §3.9 — insert — ambiguity — device-to-policy property tie is enforced for warranty claims too; body FKs resolve device → event → policy — `routes_claims.py:97-136`
- §3.9 — insert — ambiguity — eventless warranty claims escape both the filing window and the duplicate check — `routes_claims.py:138`
- §3.9 — insert — ambiguity — wrong-role verb → `ERR_UNAUTHORIZED` ahead of ownership/status; foreign `SUPPLY_INFO` → `ERR_NOT_RESOURCE_OWNER` — `routes_claims.py:186-197`
- §3.10 — insert — ambiguity — in-flight claim block reuses `ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER`, checked after the quiet-house rule — `routes_transfers.py:111-120`
- §3.10 — insert — ambiguity — acceptance demotes to `LEARNING` unconditionally; only suspension/clawback needs a `COMPLETE` profile — `services.py:763-772`
- §3.10 — insert — ambiguity — sweep transfer expiry realigns `baseline_ready` to the profile test — `services.py:737`
- §3.10 — insert — ambiguity — closure forces `baseline_ready` false on decommissioned devices — `services.py:805`
- §3.10 — insert — ambiguity — closure stamps `resolved_at` on force-resolved events — `services.py:822`
- §3.10 — insert — ambiguity — closure resets `current_credit_tier_pct` to 0 on every terminated policy, with no clawback — `services.py:850`
- §3.10 — insert — ambiguity — approved-claim scan spans device-owned and `submitted_by_user_id` claims; the already-deactivated check runs first — `routes_accounts.py:203-211`, `services.py:861-870`
- §4 — insert — ambiguity — enumerated the resource returned by each verb-style write, plus the two non-resource responses — `routes_devices.py`, `routes_events.py`, `routes_claims.py`, `routes_transfers.py`, `routes_insurance.py`

## Pipeline verification (orchestrator) — 2026-09-01T13:06:54.908141911Z

Independent 8-round parallel sweep re-run by the orchestrator after Step 9, using `--start-command "cd <impl> && bash start.sh" --isolation per-test-server`: **150 passed / 0 failed / 0 errors / 150 total in all 8 rounds**. `results.1.json`–`results.8.json` from this sweep are retained in `workspace/implementation/`.

Note: three earlier orchestrator sweep attempts failed for harness-invocation reasons on my side, not implementation reasons — a relative `bash start.sh` launcher path (the runner spawns the start command from its own cwd, so every test errored with "API server could not be restarted"), and one `pkill -f app.py` that matched the sweep's own shell (exit 144). The corrected invocation passes cleanly.
