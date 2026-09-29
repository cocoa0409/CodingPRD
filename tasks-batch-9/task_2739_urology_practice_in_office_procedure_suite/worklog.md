# Worklog — task_2739_urology_practice_in_office_procedure_suite

## Step 1: Create task directory — 2026-09-04T14:03:30.241Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2739_urology_practice_in_office_procedure_suite` and its `workspace/` subdirectory. Index 2739 was pre-assigned by the invoking pipeline (no auto-allocation scan performed, per instruction, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T15:51:11.500Z

All three scaffold artifacts are complete and the linter is clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2739_urology_practice_in_office_procedure_suite/`
- `SCAFFOLD.yaml` — 3315 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys); 12 entities, 9 state machines, 4 §1.2.1 OCC rules, 6 calculations, 44 ordered validations, 62 endpoints, 64 errors, 7 roles
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1951 lines, single top-level key, 9 rule_ids × 2 = 18 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4338 lines, single top-level key, all 9 guide sections, 73 instances (55 with full recipes + 18 `excluded_because:` stubs)

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2739_urology_practice_in_office_procedure_suite/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2739_urology_practice_in_office_procedure_suite/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2739_urology_practice_in_office_procedure_suite/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1013

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Clean on the first run against the finished file; no iteration was needed.

## Independent checks beyond the linter
- All 64 declared error ids are triggered somewhere across the two design files (0 orphans).
- All 62 declared endpoints are hit by at least one structured call (the last 8 collection GETs were covered by adding `entity_listing_remaining_collections_and_empty_page`).
- Placeholder closure: every `${var}` in a call or assert is captured by an earlier call in the same instance (0 violations); every `expected_*_version` is a `${var}`, never a literal.
- Names unique across the union of both design files; every stub's `difficulty_instance` resolves to a real §1.8 instance and no stub carries a `test_recipe`.

## Two SCAFFOLD.yaml defects found and fixed while authoring §1.9
1. `PelvicHealthReferral.status` declared LOG only as `ACCEPTED → COMPLETED` and VOID_LAST only as `COMPLETED → ACCEPTED`. That made a partial visit log an undeclared transition and made `ERR_VISIT_ALLOCATION_EXHAUSTED` (priority 76) unreachable — priority 22 would always answer first. Added `ACCEPTED → ACCEPTED` for both LOG and VOID_LAST, with a note pinning the resulting priority order.
2. Wrong enum members caught against §1.1 before they reached the recipes: `PELVIC_HEALTH_COORDINATOR` (the declared `Provider.role_type` member is `PELVIC_COORDINATOR`), and `Specimen.chain_status` is `ACCESSIONED`, not `RECEIVED`.

One authoring decision worth flagging: the claim-extraction guide's Table 6 (Errors) has prose but no claim-type rows, so `section: errors` instances reuse `violation_to_error` from Table 4 rather than coining a new token, per SKILL.md's ban on inventing `claim_type:` names.

## Step 3: Copy shared files — 2026-09-04T15:51:27.699Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T16:12:30.713Z

PRD generation complete.

## Output

`workspace/PRD.md` — **520 lines, 120,262 bytes**, built in 12 chunked `cat >>` appends (no single Write, no truncation). The file ends at a real section boundary: the final line is the last data row of the §5 error table (`| `ERR_VISIT_ALLOCATION_EXHAUSTED` | 422 |`). No audit footer, no trailing prose, nothing mid-sentence.

## Structure

- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: RBAC/identity, the byte-verbatim §2.2 envelope block, pagination, identity/timestamps/`version`, the logical clock, the four stale-version guards, precision & calendar arithmetic, the 44-rung validation ladder, reference resolution & reverse reachability, conserved ledgers, filtered collection reads
- `## 3. Business Logic & Workflows` — 9 subsections: reference data, occupancy-window arithmetic, room calendar, prep/clearance/prophylaxis, sterile processing, consignment billing, readiness/check-in/completion, pathology & the notification loop, recalls/sweep/pelvic-health referrals
- `## 4. Endpoint Definitions` — intro paragraph + 4-column table, **62 rows**
- `## 5. Error Code Catalogue` — intro paragraph + 2-column table, **64 rows**

## Hard Contract results

**Contract 1 — Field-Name Coverage: PASS.** Three mechanical passes against SCAFFOLD.yaml:
1. 161 names (all entity fields incl. `common_fields`, all endpoint request-body/query/path inputs, all computed-report output keys, all envelope/pagination keys, `current_utc`/`to_iso8601`) → **0 missing**, each present verbatim in backticks.
2. 105 enum constraint values + every state-machine state → **0 missing**.
3. Every endpoint input name re-checked against §1–§3 prose only (excluding the §4 table, so no name is "covered" by the table alone) → **0 missing**.

**Contract 2 — Rule Coverage: PASS.** All 44 validations appear as numbered rungs in §2.8 with check prose, error ID, HTTP status and `applies_to` scope (automated priority check: 44/44 found). All 9 state machines and every declared transition are described, including the self-loops (reschedule, prep-acknowledgement, leak-test-on-`AVAILABLE`, `ATTEMPTED`→`ATTEMPTED`, visit `LOG`/`VOID_LAST`) and both true cycles (`OVERDUE`→`SCHEDULED_DUE`, `COMPLETED`→`ACCEPTED`). All 6 calculations including both dual variants (`PROVISIONAL`/`FINAL` billing, `PROTOCOL_ANCHORED`/`EVENT_ANCHORED` recall dating) with every constant table written out. All 4 OCC rules in §2.6. Both cascades (A: 3 hops, B: 4 hops) plus the quarantine cascade. All field-level defaults, the three validation-priority pairs, and the sibling-branch symmetry pairs (`INTACT`/`COMPROMISED`, cancel/no-show, `ACCEPT`/`DECLINE`/`WAITLIST`/`WITHDRAW`) at equal density.

**Contract 3 — §3 Path Purity: PASS.** 1,219 backticked tokens in §3 scanned: 0 begin with `/`, 0 are a bare HTTP method, 0 combine method+path. `grep` confirms **0** raw `/urology` occurrences and 0 HTTP verb words anywhere in §3.

## Notes for the caller

- The scaffold actually holds **62 endpoints and 64 error codes**, not the 56/59 I had recorded earlier from a partial read; both tables are generated from the YAML so they are complete.
- One error-ID slip was caught and fixed during verification: the §4 intro had invented `ERR_UNAUTHORIZED_ROLE`; corrected to the scaffold's `ERR_UNAUTHORIZED`. A cross-check now confirms the PRD's error-ID set is exactly the scaffold's 64, with no extras and none missing.
- One fuzzy phrase ("as appropriate", on the priority-30 rung) was replaced with an explicit pointer to the §2.6 parent mapping.
- Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read; no `pkill` was run. Only `PRD.md` was written — `workspace/` contains just `INSTRUCTION.md` and `PRD.md`, and `worklog.md` at the task root was left untouched.
- Where the scaffold was silent I resolved the gap in prose using an existing error code rather than inventing one (e.g. administering a non-`ORDERED` antibiotic, assigning a scope to a case that needs none, and completing a case with a still-`COLLECTED` specimen all answer `ERR_INVALID_CASE_TRANSITION`). One genuine internal tension is worth flagging: `Specimen.collected_by_provider_id` is documented in the scaffold as requiring `role_type` `RN`, yet specimen collection is authorised for `Urologist` as well, and no error code exists for that constraint — the PRD therefore states only the enforceable rule (the collector must be the acting user, else `ERR_ACTOR_IDENTITY_MISMATCH`).

ORCHESTRATOR VERIFICATION: independently confirmed PRD.md is 520 lines / 120,262 bytes, ends on a complete `| `ERR_VISIT_ALLOCATION_EXHAUSTED` | 422 |` table row (a real section boundary, not mid-sentence), and contains all five top-level sections (`## 1.` Introduction through `## 5.` Error Code Catalogue). Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T17:12:06.584Z

Stage 5 test generation is complete and fully verified.

## Deliverables

**`test_helpers/`** (9 modules, task root) — `__init__.py`, `constants.py`, `types.py`, `api_client.py` (62 endpoint methods), `api_errors.py` (64 `ERR_*` constants + HTTP-status map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `test_users.py`, `fixtures.py` (4-tier builders + `Roster`).

**`test_suite/`** — `conftest.py` + 18 numbered test modules, **183 tests**.

## Coverage audit (scripted, zero problems)

| Check | Result |
|---|---|
| Difficulty instances covered | **18/18**, every one with >=2 tests |
| Corner non-stub instances covered | **55/55** |
| `excluded_because:` stubs translated | none (correct) |
| Tags per test | exactly 1, always the final docstring line, all resolve to real instances |
| PRD citations | every quoted span >=40 chars is verbatim-greppable in `workspace/PRD.md` |
| Banned vocabulary outside tag lines | none |
| `py_compile` / module import / pyflakes | all clean |
| Duplicate test or module names | none |
| Strays under `workspace/` | none; `worklog.md` untouched (mtime predates Stage 2) |

The 54-vs-55 count from the earlier segment is resolved: 73 `name:` instances - 18 distinct stub names (19 `excluded_because:` lines, one instance carrying two) = **55**.

## Notable findings

**One real bug I fixed in `test_helpers/fixtures.py`:** `run_full_reprocessing_cycle` closed each stage log with `attested_by_provider_id = tech_alt["id"]` while sending `tech_headers`. PRD §2.8 priority 16 requires `attested_by_provider_id` to *equal* `X-User-ID`, so every call would have returned `ERR_SEGREGATION_OF_DUTIES` (403) and broken setup in any test using it. Changed to `roster.tech_alt_headers`. Also removed two unused imports.

**Design-recipe defects corrected in favour of the PRD** — worth flagging because these are exactly where a recipe-following implementation will diverge from the tests:
- `device_class: BIOPSY_KIT` / `URODYNAMIC_CATHETER` -> `BIOPSY_NEEDLE` / `URODYNAMICS_CATHETER_KIT` (not enum members).
- Non-enum `ProcedureType.code` values (`CYSTOSCOPY_KIT`, `BX_CONSIGN`) and prep codes (`NPO_AFTER_MIDNIGHT`, `ANTICOAG_HOLD`, `SHOWER_CHG`) replaced with declared members.
- **Turnover arithmetic**: two recipes asserted `turnover_minutes 10` / earlier `block_end_at`; PRD §3.2 gives 10 x 2 (HIGH cleanup) = 20 above the 15-minute floor. The tests assert the PRD value.
- A recipe claimed `outstanding_recall_count` stays "2" across a supersede; its own prior step puts it at 1. Tests assert 1.
- Several trigger orders were reordered where the PRD would refuse them (completing a case with a specimen still `COLLECTED`; commissioning an `IN_USE` scope; a `DEVICE_NOT_RESERVED` probe pre-empted by `ERR_CHECKIN_TOO_EARLY`).
- Assertions on values the PRD never states (fresh-draft nullity of `device_lot_id`/`device_quantity`, `antibiotic_allergy_class` "still null" — PRD defaults it to `NONE`) were dropped or converted to unchanged-from-snapshot rather than weakened guesses.

**One residual ambiguity for Step 7:** opening a `PRECLEAN` log on a never-used `AVAILABLE` scope. PRD §3.5 names `SOILED` in the standing exception and requires the stage be "the immediate successor of the scope's last closed passing stage"; with no closed stages, `PRECLEAN` is the only coherent reading. `test_15` avoids it by driving the scope to `SOILED` through a real case; `test_10` relies on it succeeding.

No instance was skipped anywhere, and no `skip`/`xfail` markers exist in the suite.

## Step 6: Generate implementation — 2026-09-04T16:52:16.720Z

The implementation is complete and verified.

## What was built

`workspace/implementation/`

- `start.sh` — guarded `pip install` (only when Flask is missing, so per-test reboots are fast) then `exec python3 app.py`; binds `0.0.0.0`, `PORT` env with default 10000.
- `app.py` — Flask entry point, `strict_slashes = False`, registers seven blueprints under the `/urology` prefix, plus handlers for `ApiError`, 404, 405, 400 and a catch-all.
- Core modules: `constants.py` (every pinned table), `util.py` (clock/ISO-8601 with exactly 3 fractional digits, calendar month arithmetic with day clamping, ROUND_HALF_UP), `errors.py` (64 error IDs and statuses), `response.py`, `validate.py`, `middleware.py` (RBAC + actor-identity rungs 1/2/3), `db.py` (in-memory dicts only).
- `services/`: `calc.py`, `cascades.py`, `serialize.py`, `query.py`.
- `routes/`: `reference.py`, `cases.py`, `antibiotics.py`, `reprocessing.py`, `specimens.py`, `recalls.py`, `referrals.py`.

## Verification

- **Endpoint coverage is exact**: PRD §4's table has 62 method/path rows; the app registers 62. A mechanical diff shows zero missing and zero extra.
- **Error catalogue is exact**: a script parsed §5 into `{error_id: http_status}` and diffed it against `errors.HTTP_STATUS` — 64 vs 64, no mismatches.
- All `.py` files pass `python3 -m py_compile`.
- **Fresh boot is empty**: all 12 collections return `total_count: 0`, and the clock reads `2026-08-01T00:00:00.000Z`. No seeding, no SQLite, no disk or `/tmp` persistence (grep for `open(`, `json.dump`, `sqlite3`, `pickle` returns nothing).
- Two end-to-end HTTP smoke scenarios pass with zero failures (~60 assertions + 35 assertions), covering the pinned arithmetic and both ladder-ordering pairs: turnover floor-then-scope, `2369`/line provisional -> `7107` for three lines and `6807` FINAL with the volume rebate, room half-open vs. provider closed-interval boundaries, `ROOM_CLOSED` beating the calendar conflict, `LOT_EXPIRED` beating insufficient stock, `CASE_NOT_CLEARED` beating the antibiotic gate, the AUTO tie-break to CEFAZOLIN plus allergy/eGFR exclusions and renal half-dosing, segregation of duties, the five-stage reprocessing cycle and FAIL quarantine, the MALIGNANT -> escalation -> recall cascade, the three-attempt notification backoff, recall supersession with the 2026-03-31 + 24 month clamp, sweep OVERDUE/lapse_days, cancel-releases vs. no-show-wastes, and the referral visit ledger with `VOID_LAST`.

## Notes

- Three initial smoke failures were bugs in my scratch scenario, not the app: missing `clearance-review` before check-in, a provider calendar collision, and an incorrect STONE/LOW interval expectation (PRD line 350 pins it at 24 months, so `2028-03-31` is correct).
- One PRD ambiguity resolved deliberately: a patient's `version` bumps only where the PRD says a patient counter is recomputed, deduplicated per request via a new `db.touch_once`. So an `INSUFFICIENT` result (cascade stops after hop 1) and `POST /recall-sweeps` (no stored patient field changes) leave patient versions alone.
- No servers left running — all six smoke ports confirmed closed, killed by recorded PID only, never a pattern kill. `worklog.md` untouched; `test_helpers/` and `test_suite/` were never read or listed.

ORCHESTRATOR NOTE (Steps 5/6): launched concurrently in overlapping background agents so the implementation generator could not observe `test_suite/`. Verified afterwards: `test_helpers/` and `test_suite/` both sit at the task root, `find workspace -name 'test_*' -type d` returns nothing (no stray test dirs to relocate), and `test_suite/` holds `conftest.py` + 18 modules totalling 183 test functions.

## Step 7: Run tests and iterate — 2026-09-04T17:42:49.364Z

Loop complete — clean 8-round parallel sweep.

## Summary

**Iterations run:** 2 (iteration 1's sweep was the pre-existing one the orchestrator relayed; iteration 2 was my own full 8-round `setsid nohup` sweep after fixes).

**Final sweep:** all 8 parallel rounds report `total=189 passed=189 failed=0 errors=0`. Both original failures were deterministic (identical in all 8 rounds) — no flakiness anywhere in the suite.

**Tests deleted:** none deleted outright. One assertion removed under STEP 1c partial-coverage handling:

- `test_10_entity_lifecycle.py::test_room_version_advances_by_one_on_each_administrative_edit` — removed only the `updated_at > created_at` assertion. **Pattern: computed-field / temporal silence.** PRD §2.4 says only that a mutated row has "its `updated_at` refreshed"; it never states `updated_at` must be strictly later than `created_at`. PRD §2.5 mandates that "Nothing in this system reads the host machine's wall clock" and that the logical clock "must never fall back to real time," advancing only when a `PracticeAdmin` sets it — and this test never sets it. So two divergent PRD-faithful readers exist: one stamping both timestamps from the frozen logical clock (equal values, test fails) and one stamping from wall time (test passes); the former is the more faithful reading of §2.5. Unique derivability broken. The rest of the test — `version` 1->2->3 across two edits, field persistence, `created_at` stability, and three-fractional-digit rendering of both instants — is verbatim covered by §2.4/§3.1 and was kept intact. Scaffold rule that drove generation: `Corner/entities/entity_system_fields_envelope_and_version`.

**Fixes applied to `test_helpers/`:** none — the fixture/factory/header layer was faithful throughout.

**Fixes applied to `test_suite/`:**

- `test_16_rbac.py::test_collection_accession_and_completion_admit_their_partners` — the test wrapped `_clear_and_admit_case_one(api, stage)` in `validate_success(...)`, but that local helper already returns the validated `data` dict (its own final statement is a `validate_success` call). The double wrap fed a `dict` to the runner's `validate_success`, which reached for `.status_code` and raised `AttributeError` before any PRD rule was exercised. Changed to consume the helper's return value directly. Assertions untouched — the test still checks `schedule_status=IN_ROOM`, `checked_in_at`, empty `blocking_reason_codes`, and the urologist/liaison/urologist partner-role chain through collection, accession and completion.

**Fixes applied to `implementation/`:** none. Neither failure traced to a server-side defect; the implementation was already PRD-faithful on both rules, and I removed no PRD-required check.

Relevant paths:
- `test_suite/test_10_entity_lifecycle.py`
- `test_suite/test_16_rbac.py`
- `workspace/implementation/results.{1..8}.json`

`worklog.md` was not modified.

ORCHESTRATOR NOTES (Step 7): the first sweep's agent turn was killed by a transient API error about 4 minutes in, but because the sweep was wrapped in `setsid nohup` it survived and ran to completion — confirming the reaping guard works. I read the 8 result files myself and resumed the SAME agent via SendMessage with the computed union failure set (2 deterministic failures) rather than respawning a fresh agent, so its protocol context was preserved. Independently verified the final sweep afterwards: all 8 `results.$i.json` are freshly written (17:32), each reports total=189 passed=189 failed=0 errors=0 with an empty non-passing list, per-round wall time ~361s, and `grep` finds no `skip`/`xfail` markers anywhere in `test_suite/`.

Step 8 is NOT skipped: Step 7 ran a second iteration with one `test_suite/` fix and one assertion removal, so PRD-silence sites exist to patch (even though `implementation/` needed no fixes).

## Step 8: Finalize PRD — 2026-09-04T17:51:40.676Z

Done. `PRD_FINALIZED.md` written with a single one-line patch.

**Line counts:** PRD.md 520 lines / PRD_FINALIZED.md 520 lines — 1 line revised, 0 added, 0 deleted (0.19% of lines touched; +~470 chars).

**Changes**

- §2.4 (Resource Identity, Timestamps and the Version Counter), line 82 — revise — pinned that `created_at`/`updated_at` are stamped from the logical clock of §2.5 and never from real time; `created_at` is the insertion-time logical instant and never changes; each `updated_at` refresh writes the then-current logical instant, so `updated_at` need not be strictly later than `created_at` and equals it when the clock has not moved — `implementation/db.py:67-71` (`new_row`: `now = store.now()` for both) and `db.py:80-83` (`touch`: `updated_at = store.now()`, `version += 1`).

**Step 7 item 2 — no PRD edit.** `test_16_rbac.py::test_collection_accession_and_completion_admit_their_partners` was a pure test-harness bug (double `validate_success` wrap of a helper that already returned the validated dict, so `AttributeError` on `.status_code`). No PRD rule was reached, no impl behavior was pinned, so nothing in PRD_FINALIZED.md changed for it.

**Per-edit pre-edit search log (edit 1)**

(a) Subject: the source and mutual ordering of the `created_at` / `updated_at` instants on every row.

(b) Impl paths enumerated (grepped/read): `grep -rn "created_at|updated_at"` over all impl `.py` — only writers are `db.py:70-71` (`new_row`) and `db.py:82` (`touch`); readers are `services/serialize.py:8-9,41` (COMMON envelope), `db.py:52-53` (`all_rows` ordering, ties by `_seq`), `services/calc.py:163`, `services/cascades.py:44,69`. Confirmed every row is created through `db.new_row` (`grep -rn "insert("` -> only `db.py:47` definition and `db.py:76` callsite), so no path stamps timestamps from client input. `grep -rn "datetime.now|utcnow|time.time|date.today"` -> zero wall-clock reads anywhere; all instant sources are `store.now()`/`store.today()` (`routes/cases.py:366,387,428`, `routes/specimens.py:63,110,140`, `routes/reprocessing.py:98,178`, `routes/reference.py:333`, `routes/recalls.py:79`, `routes/referrals.py:109-110`, `services/calc.py:277`, `services/cascades.py:85`, `response.py:17`). Also read the clock endpoint `routes/reference.py:420-427`.

(c) Wording adjustments made: two. First, I dropped a clause asserting that rows created without an intervening clock move "share the same `created_at`" — true of the impl, but it draws in the list-ordering tie-break (`db.py:53` breaks `created_at` ties by insertion `_seq`), which no Step 7 item exposed; leaving it out keeps the edit inside scope. Second and more important, my first draft said `updated_at` "is never earlier than `created_at`" — `routes/reference.py:421-427` accepts any `to_iso8601` and assigns `store.clock` with no monotonicity check, so an admin can move the clock backwards and a subsequent `touch` will write an `updated_at` strictly earlier than `created_at`. That universal would have been a brand-new mismatch, so I replaced it with the purely mechanical statement (each refresh writes the then-current logical instant; equality when the clock has not moved), which holds on every enumerated path including the backwards-clock one.

ORCHESTRATOR VERIFICATION (Step 8): confirmed `PRD_FINALIZED.md` exists at 520 lines / 120,755 bytes and `diff` against PRD.md shows exactly one changed line (82c82), an in-paragraph revision with no new sections — genuinely minimal, and correctly NOT byte-identical since Step 7 did run a second iteration.

## Step 9: Complete PRD — 2026-09-04T18:15:39.793Z

Run as THREE sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying, so no pass clobbered an earlier one). Partition: pass 1 = core/envelope/RBAC/clock/validation-machinery/serialization/listing + `routes/reference.py`; pass 2 = `routes/cases.py`, `routes/antibiotics.py`, `routes/reprocessing.py`, `services/calc.py`; pass 3 = `routes/specimens.py`, `routes/recalls.py`, `routes/referrals.py`, `services/cascades.py`.

### Pass 1 (core + reference data) — 17 edits

**Setup:** performed the `cp PRD_FINALIZED.md -> PRD_COMPLETED.md`. **File safety:** 520 lines / 120,755 chars -> 520 lines / 126,548 chars (+5,793), 16 hunks, all single-line in-place replacements. **Counts:** 15 ambiguity-pins, 2 mismatch-revisions.

- §2.1 — insert — ambiguity — an `X-User-Role` outside the seven recognised roles binds to no role and is `ERR_UNAUTHORIZED` (403), not a malformed request — middleware.py:44-57
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric characters — util.py:26-27
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, never real time, so it repeats while the clock is still — response.py:16-18
- §2.3 — insert — ambiguity — a blank `limit`/`offset` value falls back to the default; `offset` has no upper bound and an out-of-range offset returns an empty page — validate.py:139-149
- §2.3 — insert — ambiguity — rows sharing a `created_at` are ordered by insertion sequence (the common case, since the clock is static) — db.py:53
- §2.5 — insert — ambiguity — the clock is *set*, not advanced (backwards moves legal), and `data` carries `current_utc` as its only field — reference.py:421-427
- §2.7 — insert — ambiguity — instant inputs tolerate `T`/space separator, absent seconds, any fractional width, `Z`/±offset/no zone (read as UTC); rendered back at exactly 3 digits with finer precision truncated; date fields strictly `YYYY-MM-DD` — util.py:13-16,30-37,46-80
- §2.8 rung 6 — insert — ambiguity — JSON `null` counts as absent (required fails, optional defaults); absent/empty body = empty object; non-object body fails; unnamed properties ignored except the four computed case fields — validate.py:15-37,127-131
- §2.11 — insert — ambiguity — filter matching is exact/case-sensitive and conjunctive; enum filters reject non-members with `ERR_INVALID_REQUEST`; the three boolean filters accept only true/false/1/0 in any case; identifier filters accept any string and yield an empty page; blank and undeclared query params are ignored — validate.py:163-188, query.py:9-18
- §3.1 (roster) — **revise** — **mismatch** — `npi` was declared "ten-character ... unique across the roster"; impl stores any string with no length or uniqueness check and there is no duplicate-`npi` error — reference.py:34
- §3.1 (roster edits) — insert — ambiguity — `null` leaves `credential_status`/`hld_certified` alone but *clears* `ultrasound_accreditation_expires_on`; version increments unconditionally, even on an empty payload — reference.py:51-66
- §3.1 (patients) — insert — ambiguity — `egfr` may be fractional; `primary_urologist_id` resolution ignores `credential_status` and reports both miss cases as `ERR_PROVIDER_NOT_FOUND` — reference.py:102,115-117
- §3.1 (patient edits) — **revise** — **mismatch** — PRD said "the treating `Urologist`"; impl runs no ownership check, so any roster `Urologist` may edit any patient (plus null-as-no-change and unconditional version bump) — reference.py:127-145
- §3.1 (rooms) — insert — ambiguity — `null` leaves `room_status`/`turnover_minutes` alone but clears the nullable accreditation pair; version increments unconditionally — reference.py:199-221
- §3.5 (commissioning) — insert — ambiguity — `attesting_provider_id` must merely resolve (`ERR_PROVIDER_NOT_FOUND`); no self-identity, role, credential or HLD requirement, and it is not persisted — reference.py:327-334
- §3.6 (supplier return) — insert — ambiguity — `quantity` is a required non-negative integer, 0 is accepted as a no-op that still re-bills FINAL and bumps `version`, and `lot_expires_on` is not consulted — reference.py:386-397

**Verified-clean (no edit needed):** the §5 error catalogue is an exact ID-and-status match with `errors.py` (no extras either way); §4 role lists match every `@authenticate(...)` in all route modules; the §2.11 filter inventory matches every `query.collection` call; §2.4/§2.6/§2.10 version and ledger prose, `add_months` clamping, half-up rounding, and the §3.8 "Saturday or Sunday in UTC" weekend test all already pin what impl does.

### Pass 2 (cases, antibiotics, reprocessing, calc) — 20 edits

No `cp` was run; all 17 of pass 1's edits verified intact. **File state:** 520 lines (no shrink), 130,161 chars; +3,613 chars from this pass; all 30 hunks single-line in-paragraph substitutions. **Counts:** 17 ambiguity-pins, 2 mismatch-revisions.

- §3.2 — insert — ambiguity — `primary_provider_id` need only resolve; its `role_type` and `credential_status` are never consulted — routes/cases.py:79
- §3.2 — insert — ambiguity — `scheduled_start_at` is never compared to the logical clock at draft/schedule/reschedule, so a past start is accepted — routes/cases.py:66,131,176
- §3.2 — revise — ambiguity — draft's remaining initial values pinned (`device_quantity` 0; `clearance_block_reason`, `scope_asset_id`, `device_lot_id`, `checked_in_at`, `completed_at`, `cancel_reason_code` null) — routes/cases.py:84-101
- §3.3 — insert — ambiguity — no-show never parses the request body — routes/cases.py:422
- §3.4 — insert — ambiguity — `channel` is a required string that is validated and discarded, never stored on the case — routes/cases.py:207
- §3.4 — insert — ambiguity — a repeat acknowledgement still increments the case's `version`/`updated_at` — routes/cases.py:221-224
- §3.4 — insert — ambiguity — `requested_agent` stored verbatim (`AUTO` included); `agent` filter ranges over the four formulary drugs only so `agent=AUTO` is `ERR_INVALID_REQUEST`; ordering is not gated on case `schedule_status`; any number of orders per case — routes/antibiotics.py:58-74,115
- §3.4 — insert — ambiguity — `prophylaxis_window_start_at` is never recomputed, while the window's upper bound is read live from the case's current `scheduled_start_at` — routes/antibiotics.py:67,90
- §3.5 — insert — ambiguity — a second scope assignment overwrites `scope_asset_id` and leaves the displaced scope at `IN_USE` — routes/cases.py:303-306
- §3.5 — insert — ambiguity — a log's `case_id` need only resolve; no link to the scope is required — routes/reprocessing.py:64
- §3.5 — insert — ambiguity — no closed passing log expects `PRECLEAN`; after a passing `DRY_STORE` nothing is expected — routes/reprocessing.py:36-45
- §3.5 — insert — ambiguity — a passing `PRECLEAN` on a non-`SOILED` scope leaves the scope untouched, `version` included — routes/reprocessing.py:129-132
- §3.5 — revise — **mismatch** — a passing `HIGH_LEVEL_DISINFECT` leaves `status` untouched rather than guaranteeing `REPROCESSING` (reachable on an `AVAILABLE` maintenance cycle) — routes/reprocessing.py:141-143
- §3.5 — insert — ambiguity — a passing `DRY_STORE` on a scope not in `REPROCESSING` (or without covering HLD) leaves it untouched, `version` included — routes/reprocessing.py:144-148
- §3.6 — insert — ambiguity — device reservation is not gated on the case's `schedule_status`; `quantity` 0 is accepted and still sets `RESERVED`, re-bills and bumps the lot's `version` — routes/cases.py:318-348
- §3.6 — insert — ambiguity — the volume-rebate counter is read *after* the triggering unit movement, so a completing case's own units count — services/calc.py:190, services/cascades.py:117-124
- §3.7 — revise — ambiguity — check-in never parses the request body — routes/cases.py:355
- §3.7 — insert — ambiguity — `outcome_note` is validated then discarded; the case exposes no such field — routes/cases.py:376
- §3.7 — insert — mismatch-adjacent clarification — completion does not advance the room's `version` (only schedule/reschedule/cancel/no-show do) — routes/cases.py:386-393

Everything else in the slice was already pinned uniquely: the whole occupancy-window formula and its floor-before-scope-extra order, the half-open room vs. closed doubly-buffered provider geometries, the occupying-status set, check ordering at schedule/reschedule (matches the §2.8 ladder exactly), clearance decision source sets, the seven readiness gates and their emission order, the formulary/eligibility/tie-break/dose arithmetic, escalation-clock steps, recall interval and event-anchored dating, per-line-then-sum billing, and `derive_billing_status`. Pass 2 deliberately did not touch §2.8's request-shape rung even though its "valid JSON but not an object fails here" clause does not hold for the three no-payload operations; it pinned the exception locally in §3.3 and §3.7 and flagged the third such endpoint (`POST /recall-sweeps`) to pass 3.

### Pass 3 (specimens, recalls, referrals, cascades) — 12 edits

No `cp` was run. **Final file:** 520 lines / 132,794 chars (+2,633 from this pass); 40 hunks total, all single-line in-paragraph substitutions, of which 30 are passes 1-2's (verified intact) and 10 are pass 3's. Tail still ends at the last §5 error-table row. **Counts:** 10 ambiguity-pins, 2 mismatch-revisions.

- §3.8 — insert — ambiguity — the result cascade's first hop writes the specimen row only, so an `INSUFFICIENT` result leaves the patient's `version` untouched even though the specimen enters the open notification set — routes/specimens.py:140-158
- §3.8 — insert — ambiguity — `channel` on a notification attempt is a required string, validated then discarded (no such field on the specimen) — routes/specimens.py:166
- §3.8 — insert — ambiguity — a `REACHED` outcome leaves `escalation_due_at` at its existing value; it is not recomputed against the incremented attempt count — routes/specimens.py:176-178
- §3.9 — insert — ambiguity — the patient counter recompute and single `version` increment on opening a recall are unconditional, not tied to there being a predecessor to supersede — services/cascades.py:49
- §3.9 — insert — ambiguity (**hand-off item**) — `POST /recall-sweeps` never parses a request body, so anything sent is ignored — routes/recalls.py:78-79
- §3.9 — insert — ambiguity — a recall already `OVERDUE` whose recomputed `due_on` is still past is left alone by step 2: `lapse_days` is not refreshed, it enters neither tally, and the row is written only if step 1 moved `due_on`/`due_basis` — routes/recalls.py:103-117
- §3.9 — revise — **mismatch** — the sweep no longer claims to recompute counters "for every patient it touched"; it writes only recall and specimen rows and advances no patient's `version` (derived counters surface on the next read) — routes/recalls.py:78-137
- §3.9 — insert — ambiguity — `recomputed_recall_count` counts every open recall step 1 visited, changed or not — routes/recalls.py:94-100
- §3.9 — revise — ambiguity — "a sweep that finds nothing to do" restated as "no open recall and no waiting notification", so it cannot contradict the counter pin above — routes/recalls.py:82-96
- §3.9 — revise — **mismatch** — `therapy_start_by` is recorded but never re-enforced; the therapy-start window is tested only at acceptance and a visit logged after that date is accepted normally — routes/referrals.py:151-186 (no check) vs routes/referrals.py:110
- §3.9 — insert — ambiguity — a referral declined out of `WAITLISTED` retains its `waitlist_position` (only ACCEPT and WITHDRAW clear it) — routes/referrals.py:125-127
- §3.9 — insert — ambiguity — waitlist positions are never renumbered when a referral leaves `WAITLISTED`, so a later referral may be granted a position another already holds — routes/referrals.py:130-137

Pass 3 confirmed the `POST /recall-sweeps` no-body exception is pinned locally in §3.9 (§2.8 itself untouched), verified against `routes/recalls.py:78` that `recall_sweep` never calls `validate.get_body()`. Already-correct areas needing no edit: specimen collection preconditions/defaults/uniqueness scope, the two accession branches and the 24-hour transit rule, the four-step escalation clock, the attempt ladder to `FAILED` at 3, `EVENT_ANCHORED` recompute and its tie-break, supersession ordering and `predecessor_recall_id` selection, recall close, the `min` of three numbers on ACCEPT, WITHDRAW forfeiture, `VOID_LAST` reversing the most recent log by insertion order, the ledger identity, and all three collection filter sets. Cascade helpers outside the recall path (`soil_scope`, `release_scope`, `move_device_units`, `cancel_open_antibiotic_orders`) were already fully pinned by pass 2's §3.3/§3.6/§3.7 prose.

### Orchestrator verification (Step 9)

- `PRD_COMPLETED.md` is 520 lines / 132,794 bytes and is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs) — the scan genuinely ran; 40 diff hunks total across the three passes, 49 pins/revisions.
- Structure intact: all 5 top-level sections present, tail still ends on the complete `| `ERR_VISIT_ALLOCATION_EXHAUSTED` | 422 |` row. No truncation, no new sections, no line-count shrink at any pass boundary.
- `implementation/` and `test_suite/` were untouched by Steps 8 and 9 (latest mtime 17:25, predating the final all-green sweep at 17:32), so the clean 8-round result still describes the shipped artifacts. No re-sweep needed — Steps 8/9 only edit documentation.

PIPELINE COMPLETE — Step 9 has written `workspace/PRD_COMPLETED.md`.
