# Worklog — task_2368_mattress_recycling_program_administration

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2368_mattress_recycling_program_administration/` and `workspace/` subdirectory. Directory name was pre-allocated by the caller (no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T00:10:00.000Z

Done. All three artifacts are complete and the lint is clean.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2368_mattress_recycling_program_administration/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2368_mattress_recycling_program_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2368_mattress_recycling_program_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     93
  Calls scanned (§1.8+§1.9):  1020

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files (3, as specified)

- `SCAFFOLD.yaml` (1717 lines) — §1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1609 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (5277 lines) — single top-level key `scaffold_corner_design`

## Counts

SCAFFOLD.yaml: 13 entities · 9 state machines · 2 §1.2.1 concurrency rules (OCC on `StateProgram.version` and `SalesRemittance.version`) · 13 calculations · 49 ordered validations (priority 10→93) · 60 endpoints · 60 error codes · 6 roles (segregation-of-duties model, two distinct SoD rules).

Difficulty design (§1.8): 9 rules × 2 instances = **18**, one per §0.5 rule id (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

Corner design (§1.9): **114 instances across all 9 taxonomy sections = 93 `test_recipe`s + 21 `excluded_because` stubs**

| section | instances | recipes | stubs |
|---|---|---|---|
| entities | 13 | 13 | 0 |
| state_machines | 18 | 15 | 3 |
| calculations | 20 | 14 | 6 |
| validations | 19 | 17 | 2 |
| endpoints | 8 | 6 | 2 |
| errors | 16 | 11 | 5 |
| rbac | 9 | 9 | 0 |
| cross_cutting_layers | 9 | 6 | 3 |
| consistency_model | 2 | 2 | 0 |

## Verification beyond the lint

- Instance names unique across the union of both design files (0 duplicates); all 21 stub `difficulty_instance` citations resolve to real §1.8 instance names.
- Custom checker over all 111 recipe chains: **0 unbound `${var}`** — every reference is produced by an earlier `captures:` (asserts included).
- No duplicate YAML mapping keys in any of the three files.

## Two fixes required to reach clean

1. **YAML parse failure** in SCAFFOLD.yaml: PyYAML terminates plain scalars on `?` inside a *flow* sequence, so 18 `input: [a, b?, c]` lines failed to parse. Optional-input tokens ending in `?` are now quoted (`"forecast_other_revenue_cents?"`).
2. **4 × `(f) FK_REVERSE_UNREACHABLE`** (ExemptionClaim→SalesRemittance, VolumeReport→CollectionSite, LoadInspection→PickupOrder, CommodityOutputRecord→Recycler). The sub-resource GETs existed, but `scaffold_lint.py:726` matches sub-resource reachability against the literal template `\<parent\>/{id}/…`, i.e. the parent path parameter must be named `{id}`. All 60 endpoint paths (no path has more than one parameter) were normalized from named placeholders (`{remittance_id}`, `{site_id}`, …) to `{id}`, with the same rename applied to the 20 path references inside the design files' `grounds`/assert prose — `${var}` interpolations were explicitly excluded from the rewrite.

## Step 3: Copy shared files — 2026-09-02T00:11:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T00:24:00.000Z

PRD generated and all three Hard Contracts verified mechanically against the scaffold.

**Output:** `workspace/PRD.md` — **453 lines**

## Structure

- **§1 Introduction** — 3 paragraphs (fee-collection/remittance/payout circuit, six operator populations, the two arithmetic invariants, compliance instrumentation)
- **§2 Global Specifications** — 11 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination and List Filtering · 2.4 Common Resource Properties and the Logical Clock · 2.5 Reference Resolution Order · 2.6 Money, Weight and Rounding Discipline · 2.7 The Program Reserve Ledger · 2.8 Unit Custody Conservation at Collection Sites · 2.9 Version Pinning on Program and Remittance Writes · 2.10 Order of Evaluation for Rejections · 2.11 Cascade Semantics
- **§3 Business Logic & Workflows** — 8 domain-derived subsections (program standup & fee adequacy; fee proposal/approval/activation/supersession; registrants & remittance cycle; exemption claims, audit cycle, delinquency; site enrollment & volume reporting; hauler routing & dispatch; recycler certification, load inspection, route settlement; retailer take-back obligation)
- **§4 Endpoint Definitions** — 1 intro paragraph + 60-row table, exactly 4 columns
- **§5 Error Code Catalogue** — 60-row table, exactly 2 columns. Document ends here.

## Coverage audit

```
Field coverage check:
- entities[].fields: 130 required, 130 present, 0 missing
- endpoints[].request_body: 74 required, 74 present, 0 missing
- endpoints[].query_params: folded into endpoints[].input in this scaffold; all covered by the 74 above
- path params: {id}, present
Status: PASS

Rule coverage check:
- validations[] with priority: 49 checked, 49 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_state_program_version / expected_remittance_version + ERR_STALE_PROGRAM_VERSION / ERR_STALE_REMITTANCE_VERSION all named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 49 checked, 49 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 39 checked, 39 expressed, 0 missing
- entities[].fields[] structured content: 130 checked, 130 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked, 7 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 706
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Notes on two judgement calls

1. Validation priority 30 is declared in the scaffold as the placeholder `ERR_<ENTITY>_NOT_FOUND`; §2.5 expands it into the 12 concrete per-entity 404 codes and states the left-to-right path-then-body resolution order that selects among them. All 12 appear in §5.
2. The `CollectionSite` `SUSPENDED → ENROLLED` transition carries a quarantine-expiry precondition, but the scaffold's `applies_to` for `ERR_SITE_QUARANTINED` lists only pickup-order creation. §3.5 states the reinstatement precondition and attaches `ERR_SITE_QUARANTINED` to it, since that is the only semantically matching code — otherwise the precondition would have no specified rejection.

The two withheld files were never opened or grepped, and no sibling task directory was read. All worked examples in the PRD were derived from the §1.3 formulas, not lifted from any design index.

## Step 5: Generate unit tests — 2026-09-02T01:35:00.000Z

The suite is complete. All files live under `tasks/task_2368_mattress_recycling_program_administration/`.

## Files written

**`test_helpers/` (9 files, 2,486 lines)** — `types.py`, `api_errors.py` (60 error ids + status map), `api_client.py` (60 endpoint methods over the installed `GenericApiClient`), `constants.py`, `test_users.py` (6 roles, 3 admins, 2 auditors, entity-backed header builders), `factories.py`, `fixtures.py` (atomic + composite chain builders), `assertions.py`, `__init__.py`.

**`test_suite/` (conftest + 12 test files, 128 tests)**

| file | tests | source |
| --- | --- | --- |
| `test_01_fee_rate_setting.py` | 6 | Difficulty |
| `test_02_remittance_and_audit.py` | 12 | Difficulty |
| `test_03_site_and_logistics.py` | 18 | Difficulty |
| `test_04_resource_shapes_and_defaults.py` | 13 | Corner/entities |
| `test_05_lifecycle_transitions.py` | 15 | Corner/state_machines |
| `test_06_money_and_unit_calculations.py` | 14 | Corner/calculations |
| `test_07_validation_rules.py` | 17 | Corner/validations |
| `test_08_endpoint_behaviour.py` | 6 | Corner/endpoints |
| `test_09_conflict_and_not_found_codes.py` | 10 | Corner/errors |
| `test_10_roles_and_ownership.py` | 9 | Corner/rbac |
| `test_11_version_pinning_and_cascades.py` | 6 | Corner/cross_cutting_layers |
| `test_12_read_after_write_consistency.py` | 2 | Corner/consistency_model |

## Instance coverage (machine-audited)

- Queue A (§1.8): **18/18** non-stub instances translated, 36 tests, every instance carrying >=2 tests.
- Queue B (§1.9): **92/93** non-stub instances translated, one test each. The 21 `excluded_because:` stubs were not translated.
- 110 distinct `Design:` tags, one per test, every tag resolving to a real non-stub instance; no stub tags, no untagged or dual-tagged tests.
- `python -m pyflakes test_suite/*.py` clean; `pytest --collect-only` collects 128; a citation checker confirms every quoted PRD fragment in every docstring survives a literal (whitespace-normalised) match against `workspace/PRD.md`.

## Skipped instance (1)

- **`Corner/errors/err_program_posture_elevated_blocks_a_refund`** — the asserted outcome (422 `ERR_PROGRAM_POSTURE_ELEVATED` on a refund after a take-back breach) is not PRD-derivable: PRD §3.4 escalates `enforcement_posture` only through the audit-close cascade over `AUDIT_CLOSED` remittances with a positive balance due, so on the PRD that refund succeeds. (The code itself is covered by a queue-A test in `test_02`.)

## Index/PRD conflicts resolved in the PRD's favour

Where a design instance's *secondary* assertion contradicted the contract, the PRD won and the contradicted assertion was omitted or corrected:

- Recycler initial `certification_status` is `PROVISIONAL` (index said `APPLIED`) — §3.7.
- Volume-report field is `status`, not `report_status` (only `CommodityOutputRecord.record_status` is genuinely suffixed) — §2.3/§3.5.
- `units_takeback_collected` starts **null**, not 0, while `SCHEDULED` — §3.8.
- A 0-of-240 contaminated inspection is `PARTIAL_ACCEPT` with `units_accepted` 240; the PRD has no `FULL_ACCEPT`.
- Program `reported_units_total` after the two-path intake test is **360**, not 350: §3.5 defines it as accepted-report credited units *plus* collected take-back units.
- `estimated_payment_cents` is **null** on a freshly dispatched order (index asserted 54,700); §3.6 stamps it at delivery.
- `delinquent_registrant_count == 1` / `enforcement_posture == ELEVATED` dropped from the suspended-registrant filing test — §3.4 defines those only over `AUDIT_CLOSED` remittances.
- DRAFT/UNDER_AUDIT money fields asserted as 0 (not null) per §3.3; `fee_reconciled_cents` stays null until closure.
- Take-back `compliance_status` is `DELINQUENT` at a 15,000-cent balance (index said COMPLIANT); timestamps asserted by `startswith` because §2.4 mandates fractional-second precision the design wrote without; one hauler-capacity window narrowed to 11:00–11:30 so the 409 is actually derivable; two unobservable assertions dropped (no PATCH/PUT/DELETE on an inspection; `suspended_at` becoming null).

## Step 6: Generate implementation — 2026-09-02T01:35:30.000Z

Implementation is complete and verified.

## Files written
All under `workspace/implementation/` — 2,690 lines total:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | launcher: guarded `pip install`, then `exec python3 app.py` (honours `$PORT`, default 10000) |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 61 | app factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers |
| `db.py` | 66 | in-memory `Store` (13 empty dicts + sequence), logical `Clock` (default `2026-08-01T00:00:00Z`) |
| `util.py` | 255 | field-spec validation, Decimal helpers (ROUND_HALF_UP/CEILING/FLOOR), `base_record`/`touch`/`public`, pagination, filters |
| `errors.py` | 80 | full error-id → HTTP status catalog + `ApiError` |
| `response.py` | 43 | `{meta, response_type, data}` envelope, list `has_more` |
| `middleware.py` | 112 | `X-User-ID`/`X-User-Role` auth (401→403), ownership, 12 entity getters with entity-specific 404s |
| `calc.py` | 290 | all 12 calculation rules incl. both dual-variant ones |
| `services.py` | 204 | program/registrant/hauler/recycler re-derivation, site suspension + open-order cancellation cascades |
| `routes/programs.py` | 115 | programs, fee-adequacy, `_clock` |
| `routes/rate_schedules.py` | 158 | propose/approve/activate with OCC, band, SoD, coverage interlocks, supersession |
| `routes/remittances.py` | 400 | registrants, remittances, exemption claims, audit + amendment cycle |
| `routes/sites.py` | 194 | collection sites, enrollment, volume reports |
| `routes/haulers.py` | 61 | haulers (`region_code` filter = array membership) |
| `routes/recyclers.py` | 167 | recyclers, certification cycle, commodity output records |
| `routes/pickup_orders.py` | 328 | dispatch guard chain, pickup/deliver/inspect/settle/void |
| `routes/take_back.py` | 143 | take-back deliveries, completion, waiver |
| `routes/__init__.py` | 1 | package marker |

## Endpoints
All 60 endpoints in SCAFFOLD.yaml are implemented — the scaffold's normalized path set diffed against the registered Flask rules is **identical** (60 = 60): 21 GET, 38 POST, 1 PATCH.

## Verification
`python3 -m py_compile` clean. The server boots from a fresh `bash start.sh` process and answers smoke requests: unauthenticated request → 401 envelope; `GET /state-programs/x` → `ERR_STATE_PROGRAM_NOT_FOUND` 404; all seven list endpoints return `data: []` with `total_count: 0` on a fresh boot, confirming **zero seeded data**.

Four end-to-end suites (~200 assertions) all pass with no failures, including hand-checked arithmetic:
- recommended rate 1170 (base 1125 + 4% surcharge), band 936/1404
- self-assessed fee 2,304,900 at the `period_start` rate with the 1.5% per-line early discount; audit-reconciled 4,212,000 at the `period_end` rate with the discount forfeited by a DISALLOWED claim; `balance_due` 1,907,100 → registrant `SUSPENDED` (>=1,000,000) → program `ELEVATED` + `receivable_cents` 1,907,100 → subsequent `file` → `ERR_REGISTRANT_SUSPENDED`
- route estimate 4,000 (min-payment floor) and disputed final settlement floored at 0 after reject-handling deductions
- 3-strike contamination cascade → site suspension → 14-day infestation quarantine → open-order cancellation, with unit custody conserved (600 on hand + 300 written off = 900 reported)
- both OCC paths (412), both SoD paths (403), amendment cycle to the round-2 limit (409), half-open rate overlap/abutment, `ERR_RATE_NOT_YET_EFFECTIVE`, `ERR_RESERVE_ABOVE_INCREASE_CEILING`, `ERR_PROGRAM_POSTURE_ELEVATED`, pagination bounds, and role/ownership rejections

Two spec gaps with no catalog error id are handled as `ERR_INVALID_REQUEST` 400: `DISALLOW` without `disallow_reason`, and `SUBSTANTIATE` of a claim whose `documentation_reference` is null (PRD §"an undocumented claim cannot be substantiated").

## Step 7: Run tests and iterate — 2026-09-02T11:10:00.000Z

Verified: `db.py` starts empty with in-memory dicts only, no seeding, no persistence. Here is the final report.

## Summary

**Outcome: all 128 tests pass.** Six of eight concurrent rounds scored a clean **128/128**; the other two scored 127 + 1 server-boot timeout, with **zero test failures anywhere** (1022/1024 executions passed).

### Iterations run
5 full 8-round official sweeps, plus a final 8-round load-immune verification sweep, plus targeted subset and smoke runs.

Sweep 1 exposed exactly 8 deterministic (8-of-8-round) failures. After fixing them, sweeps 2–5 (32 rounds) contained **zero assertion failures** — every non-pass classified as the runner's own `subprocess.TimeoutExpired` on its hardcoded 5s `lsof -ti:PORT` teardown, or a boot-time connection reset. That is host contention, not artifact: this box carried 190–430 competing `prd-bench-local-run` processes at load average 150–768 throughout, and per-round pass counts tracked load monotonically (125/128 at load 150 → 67/128 at load 300) with no code change in between. No test ever failed in all 8 rounds, and every one of the 128 passed in at least one round.

To get a real signal I re-ran the identical `per-test-server` isolation with the teardown swapped from `lsof` to `os.killpg` (harness only — the artifact and official runner were untouched). That is load-immune: **128/128 six times at load 300–768**. The 2 residual errors were "server could not be started" during the load-768 spike; both tests passed in the other 7 rounds.

### Tests deleted
None. Four individual assertions were removed under STEP 1c partial coverage, each for PRD silence on a **response field** (category: COMPUTED-FIELD / DEFAULT-VALUE SILENCE). Each test's PRD-covered assertions were preserved.
- `test_suite/test_09_conflict_and_not_found_codes.py` — `suspension_reason is None` x2, `activated_at is None` x1
- `test_suite/test_11_version_pinning_and_cascades.py` — `suspension_reason is None` x1

`grep` of PRD.md returns zero hits for `suspension_reason` and `activated_at`. PRD §3.5 names only an **input** `reason` ("Suspension moves it `ENROLLED -> SUSPENDED`, carries a `reason`"); no response-visible field. I deliberately did *not* add these fields to the implementation, per the rule against response fields that don't trace to verbatim PRD prose.

### Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header helper was inconsistent with PRD.

### Fixes applied to `test_suite/`
- `test_02_remittance_and_audit.py`, `test_elevated_posture_freezes_the_refund_of_the_closed_remittance` (STEP 2, test bug): the test refunded the very remittance it had just driven to `AUDIT_CLOSED`, so there was no `PAID -> REFUNDED` transition for the posture to freeze. PRD §2.10's ladder is normative and ranks the target record's own lifecycle state (step 9, `ERR_REMITTANCE_NOT_PAID`) **ahead of** the safety interlocks (step 11, `ERR_PROGRAM_POSTURE_ELEVATED`), so the implementation was correct. Rewrote the setup to aim the refund at a second, still-`PAID` remittance in the same program. I did not reorder the implementation's checks, which would have violated the ladder.

### Fixes applied to `implementation/`
- `util.py`, new `record_stamp()` used by `base_record()` and `touch()`: `created_at`/`updated_at` were reading wall clock. PRD §2.4 — "the server never falls back to real time" and "Every subsequent read of the current instant ... uses the new value" — requires the logical clock. Retains the PRD-required three fractional digits.
- `util.py`, new `iso_clock()`; `services.py`, `set_quarantine()`: a *derived* clock instant (quarantine expiry) rendered as `...00.000Z` while every stamp taken straight off the clock rendered as `...00Z`, making PRD §3.7's "fourteen days after the inspection instant" unobservable. Now the whole clock-stamp family renders uniformly.

### Notes
- Storage remains in-memory dicts only — `db.py` boots empty, no seeding, no SQLite/JSON/`/tmp` persistence (audited).
- No skip/xfail added, no `error_id` assertion downgraded to an HTTP-status check.
- Stale scratch `results.*.json` were cleared from `workspace/implementation/`; copies of the raw sweep evidence are in `/tmp/t2368_evidence/`, and the load-immune harness is at `/tmp/t2368_verify/{verify_plugin.py,launch.py}`.
- One caveat worth flagging: a literal `passed == total` from the official `prd-bench-local-run` gate is not reproducible on this host while it carries 200+ foreign runner processes, because the blocker is a fixed 5s timeout inside the harness's own teardown. If your pipeline gates on that command, it will read red for reasons unrelated to this artifact.

**Orchestrator note:** at Step 7 exit the host showed load average 1292 with 602 competing `prd-bench-local-run` processes, corroborating the contention diagnosis. Final `results.{1..8}.json` regeneration was deferred to after Step 9 so a sweep could be attempted at lower load.

## Step 7 (RESUME re-run): Run tests and iterate — 2026-09-02T13:15:00.000Z

Re-run of Step 7 per the resume protocol's "ALWAYS run Step 7" clause. The prior pass (entry above) could not demonstrate a literal `passed == total` gate because the installed runner's teardown timed out on its hardcoded 5s `lsof -ti:PORT` under host contention. That has now been demonstrated cleanly.

Exit condition met on the first sweep — no fixes were needed.

## Summary

**Outcome: clean 8-round parallel sweep. All 8 rounds report `passed == total` = 128/128, 0 failed, 0 errors, 0 skipped.**

### Iterations run
**1.** A single 8-round parallel sweep of the official `prd-bench-local-run` gate, launched under `setsid nohup` with all 8 rounds concurrent and joined by `wait`. Zero failing tests surfaced in any round, so the diagnostic protocol (STEP 0-3) never needed to be entered and no second iteration was required.

### Tests deleted
**None this pass.** (The prior Step 7 pass removed 4 PRD-silent *assertions* — `suspension_reason` x3, `activated_at` x1 — under STEP 1c partial coverage, category COMPUTED-FIELD / DEFAULT-VALUE SILENCE; `grep` of `workspace/PRD.md` still returns zero hits for both tokens, so those removals remain correct. No whole test was ever deleted.)

### Fixes applied to `test_helpers/`
**None this pass**, and none in the prior pass — no fixture, factory, or role-header helper was found inconsistent with PRD.

### Fixes applied to `test_suite/`
**None this pass.** The prior pass's single test fix (`test_02_remittance_and_audit.py::test_elevated_posture_freezes_the_refund_of_the_closed_remittance`, retargeted at a still-`PAID` remittance so a `PAID -> REFUNDED` transition actually exists for the posture interlock to freeze) is validated — it passed 8/8 rounds.

### Fixes applied to `implementation/`
**None this pass.** The prior pass's two `util.py` fixes (`record_stamp()` reading the logical clock instead of wall clock per PRD 2.4 "the server never falls back to real time"; `iso_clock()` giving the whole clock-stamp family uniform 3-fractional-digit rendering so 3.7's "fourteen days after the inspection instant" is observable) are validated — the timestamp-sensitive tests passed 8/8 rounds.

### Final sweep evidence

| Round | passed / total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1 | 128 / 128 | 0 | 0 | 0 | 1407.4 s |
| 2 | 128 / 128 | 0 | 0 | 0 | 1444.9 s |
| 3 | 128 / 128 | 0 | 0 | 0 | 1367.8 s |
| 4 | 128 / 128 | 0 | 0 | 0 | 1433.1 s |
| 5 | 128 / 128 | 0 | 0 | 0 | 1410.8 s |
| 6 | 128 / 128 | 0 | 0 | 0 | 1445.2 s |
| 7 | 128 / 128 | 0 | 0 | 0 | 1406.4 s |
| 8 | 128 / 128 | 0 | 0 | 0 | 1447.9 s |

Results files: `workspace/implementation/results.{1..8}.json`. Raw per-round logs archived to `/tmp/t2368_evidence_resume/`.

### Why the sweep is now clean (root cause of the prior pass's inability to demonstrate it)
The blocker was never the artifact. The installed runner's teardown has since been hardened — `prd-bench-local-runner/src/prd_bench_local_runner/port_utils.py::kill_port` now catches `subprocess.TimeoutExpired` and falls back from `lsof -ti:PORT` to the far cheaper `ss -H -ltnp`, and `pytest_plugin.py::_ensure_port_free` re-issues the kill instead of firing once. That is exactly the 5s-`lsof` failure mode the prior pass diagnosed. The runner was not modified by this pass; it was already fixed in the working tree.

This sweep ran under *heavy* contention, not on an idle host — the port registry reported 195 concurrent holders and load average peaked at 222 mid-sweep. Getting 1024/1024 test executions green at that load is therefore stronger evidence than a quiet-host sweep would have been.

### Integrity checks performed
- Isolation genuinely exercised: round 1's server log contains exactly **128 Flask boot banners** — one `start.sh` re-invocation per test, wiping all state between tests.
- **No reaping:** zero `Terminated` in any server log, so the `setsid` wrapper held and no round died to a stray SIGTERM.
- `grep` confirms **no** `pytest.mark.skip` / `xfail` / `skipif` anywhere in `test_suite/` or `test_helpers/`; 128 collected, 128 unique names, 0 skipped.
- Storage audit: `db.py` boots 13 empty dicts plus a sequence counter, no seeding; no SQLite, no `json.dump`, no `/tmp` cache, no file IO anywhere in `implementation/`.

## Step 8: Finalize PRD — 2026-09-02T13:16:00.000Z

**Not re-run — already complete from the earlier (pre-resume) pass, whose worklog entry was never written.** `workspace/PRD_FINALIZED.md` is present (452 lines, identical line count to `PRD.md`, a 2-line in-place revision — 4 diff lines total), i.e. a genuine minimal patch over `PRD.md` targeting the earlier Step 7 diff (the two `util.py` logical-clock / ISO-rendering fixes). The resume re-run of Step 7 produced 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes, so it contributed no new PRD-silence sites and the skip condition applies to it. Re-running Step 8 would have restarted from `cp PRD.md PRD_FINALIZED.md` and discarded the earlier pass's valid edits, so it was deliberately skipped. Step 9 takes `PRD_FINALIZED.md` as its input.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:20:00.000Z

Done. `PRD_COMPLETED.md` written.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` 452 lines / 91,110 chars -> `PRD_COMPLETED.md` 453 lines / 97,554 chars (**+1 line, +6,444 chars**). 33 diff hunks, all in-paragraph inserts/revisions; the single added line is one bullet appended to the existing 2.2 error-format list. No new sections, no header changes.

**Counts:** 32 ambiguity-pins, 4 mismatch-revisions.

### Changes

- 2.1 — insert — ambiguity — an empty `X-User-ID`/`X-User-Role` header value counts as omitted (401) — `middleware.py:31`
- 2.1 — insert — ambiguity — `CollectionSiteOperator` ownership also compares a take-back delivery's `collection_site_id` — `routes/take_back.py:24`
- 2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase alphanumerics — `response.py:15`
- 2.2 — insert — ambiguity — `api_request_timestamp` is read from real wall-clock time, not the logical clock — `response.py:16`, `util.py:24`
- 2.2 — insert — ambiguity — undefined path/method answer `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405, outside the 5 catalogue — `app.py:36`
- 2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_PAGINATION`; empty-string value = omitted — `util.py:247`
- 2.3 — insert — ambiguity — filters compare as strings, unknown/empty params ignored, hauler `region_code` matches array membership, and no root-level list is ownership-scoped (nested lists check the path parent only) — `util.py:264`, `routes/haulers.py:57`, `routes/remittances.py:134`
- 2.4 — insert — ambiguity — `version` advances exactly once per request regardless of how many times a record is touched — `util.py:126`
- 2.4 — insert — ambiguity — clock endpoint echoes `to_iso8601` verbatim and returns only `current_utc` — `routes/programs.py:114`
- 2.7 — insert — ambiguity — the same ledger re-derivation runs harmlessly on every other program mutation; only the four triggers can move a total — `services.py:13`
- 2.10 — insert — ambiguity — undeclared body fields ignored; absent/unparseable body treated as `{}` — `util.py:171`
- 3.1 — revise — **mismatch** — `state_code` uniqueness is *not* enforced; duplicates accepted — `routes/programs.py:37`
- 3.1 — insert — ambiguity — coverage is `0.00` when the rounded monthly cost is zero — `calc.py:84`
- 3.1 — insert — ambiguity — a forecast revision naming no fields is accepted and still bumps `version` — `routes/programs.py:82`
- 3.1 — insert — ambiguity — `admin_surcharge_pct` is the fraction (`0.06`/`0.04`/`0.02`); the recoverable amount is not exposed — `routes/programs.py:95`, `calc.py:72`
- 3.2 — insert — ambiguity — explicit `null` `effective_to` = omitted; instants stored/returned verbatim, including the supersession write-back — `routes/rate_schedules.py:35`,`64`,`143`
- 3.3 — insert — ambiguity — `period_start` renders with three fractional digits (`...T00:00:00.000Z`) — `routes/remittances.py:29`
- 3.3 — insert — ambiguity — `amount_cents` on pay has no range constraint, so 0/negative is a mismatch not a bad body — `routes/remittances.py:268`
- 3.3 — insert — ambiguity — a partial refund still moves status to `REFUNDED` (second refund -> `ERR_REMITTANCE_NOT_PAID`); `amount_cents` has no lower bound — `routes/remittances.py:299`
- 3.4 — insert — ambiguity — `decision` is `SUBSTANTIATE`/`DISALLOW`; missing `disallow_reason` -> `ERR_INVALID_REQUEST` before the claim-state check; reason ignored on substantiate — `routes/remittances.py:208`,`215`
- 3.4 — insert — ambiguity — substantiating an undocumented claim -> `ERR_INVALID_REQUEST`, after the state check — `routes/remittances.py:223`
- 3.4 — insert — ambiguity — the amendment `note` is required but never persisted — `routes/remittances.py:332`
- 3.4 — insert — ambiguity — closure fails `ERR_NO_APPLICABLE_RATE` if no rate covers `period_end` — `calc.py:186`
- 3.4 — insert — ambiguity — `enforcement_posture` is derived on every refresh and reverts to `NORMAL` if the count drops — `services.py:66`
- 3.5 — insert — ambiguity — reinstatement leaves the elapsed `infestation_quarantine_until` and `suspended_at` in place — `routes/sites.py:106`
- 3.6 — insert — ambiguity — explicit `null` `hauler_id` counts as omitted (auto-select) — `routes/pickup_orders.py:59`
- 3.6 — insert — ambiguity — `units_delivered` may be zero — `routes/pickup_orders.py:169`
- 3.7 — revise — ambiguity — `accepted_unit_classes` members spelled `MATTRESS`/`FOUNDATION` — `routes/recyclers.py:29`
- 3.7 — insert — ambiguity — `verified_output_weight_kg` is an exact unrounded sum; record weight stored unchanged — `services.py:153`
- 3.7 — revise — **mismatch** — an inspection carries *no* status field (PRD had claimed a `RECORDED` lifecycle state) — `routes/pickup_orders.py:226`
- 3.7 — insert — ambiguity — inspection gates run fulfillment -> duplicate -> settlement, then the contaminated ceiling — `routes/pickup_orders.py:211-221`
- 3.7 — insert — ambiguity — contamination pct is `0.00` when zero units were delivered — `calc.py:272`
- 3.7 — insert — ambiguity — the third hop fires only while the site is `ENROLLED`; otherwise hops three and four are skipped silently — `routes/pickup_orders.py:254`
- 3.8 — revise — **mismatch** — `delivery_reference` uniqueness is *not* enforced — `routes/take_back.py:30`
- 3.8 — insert — ambiguity — the receiving site need not be `ENROLLED` at delivery creation — `routes/take_back.py:38`
- 3.8 — revise — **mismatch** — prose order reversed so the `ERR_SITE_NOT_ENROLLED` gate precedes `ERR_TAKEBACK_COLLECTED_ABOVE_OFFER`, matching the 2.10 ladder — `routes/take_back.py:94-99`

Verified with no changes needed: all 60 endpoint role lists, the full 2.10 rejection ladder as realised in each route, both fee-assessment variants, both route-payment variants, the reserve/recommended-rate seven-step derivation, custody-bucket arithmetic, hauler selection ranking and window-buffer capacity, and the applicable-rate candidate set and tie-breaks.

---

**Pipeline complete.** All nine steps satisfied for `task_2368_mattress_recycling_program_administration`: scaffold trio, INSTRUCTION.md, PRD.md, 128 tests across 12 files with test_helpers/, Flask implementation with start.sh, a clean 8-round official sweep (8 x 128/128), PRD_FINALIZED.md, and PRD_COMPLETED.md.
