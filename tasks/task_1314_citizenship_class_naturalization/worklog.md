# Worklog — task_1314_citizenship_class_naturalization

## Step 1: Create task directory — 2026-08-12T21:34:00.000Z

Task directory `tasks/task_1314_citizenship_class_naturalization/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher (Step 1 done out-of-band; no index scan performed per instructions).

## Step 2: Generate scaffold — 2026-08-12T22:30:00.000Z

All three scaffold artifacts are generated, verified, and lint-clean.

## What was produced

**`/home/ubuntu/github/CodingPRD/tasks/task_1314_citizenship_class_naturalization/SCAFFOLD.yaml`** (1783 lines) — compliance/audit primary archetype with quota/allocation secondary; layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers. Graph topology (junctions: Enrollment, WorkshopSeat, MockInterview), segregation-of-duties role model.
- **15 entities**: Program (singleton config carrying every threshold/fee constant), Applicant, Screening, ClassSection, Enrollment, AttendanceRecord (append-only), Volunteer, TrainingCredit (append-only), Workshop, WorkshopSeat, ApplicationPacket, FeeWaiverRequest, USCISCase, MockInterview, OathCeremony.
- **12 state machines**: cyclic packet revision loop (DRAFT→IN_LEGAL_REVIEW→NEEDS_REVISION→DRAFT), cyclic volunteer accreditation (GENERAL/LEGAL→LAPSED→renewal restores level), parallel stage×rfe_status dimensions on USCISCase, waitlist→promotion→auto-decline enrollment lifecycle.
- **4 OCC concurrency rules** (enrollment create, seat reserve, screening supersede, oath assign), each with `expected_*_version` inputs and version-bump side effects.
- **11 calculations** with pinned constants: fee-waiver tier (integer-cents poverty-guideline tiers, inclusive boundaries), filing-fee per-line round-half-up-then-sum (43752 vs the 43751 sum-first trap), attained/projected readiness weighted scoring, attendance basis-point truncation, midterm auto-revoke, seat-ledger with pinned evaluation order, 730-day training window, mock rubric with compound threshold, 84-day RFE deadline, supervised-hours ledger.
- **17 validation priorities** (request → auth → role → existence → ownership → state → safety/accreditation → SoD → temporal → overlap → referential → constraint → thresholds → fiscal → OCC), 37 error codes — every one referenced and test-covered.
- **69 endpoints**, 4 roles (`ProgramAdmin`/`IntakeCoordinator` opaque; `Volunteer`/`Applicant` entity-backed with ownership rules).

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (1521 lines) — 20 instances, every §0.5 rule ≥2: dual-variant on fee waiver (fiscal) AND readiness (scoring domain); combinatorial in all three modes (a) household/income/benefit interaction, (b) rounding-order, (c) seat-ledger evaluation order; three non-linear machines on different entities; depth-4 attendance→revoke→seat→promotion cascade and depth-3 oath-conclude→case→applicant+voter-referral cascade; state-vs-fiscal and safety-vs-temporal priority conflicts; income-ratio and attendance-bp boundaries on different endpoints/metrics; Enrollment→Screening and Packet→WorkshopSeat cross-entity gates; half-open room adjacency vs 15-minute volunteer buffer overlap semantics; seat-count and supervised-hours compensating invariants.

**`SCAFFOLD_CORNER_DESIGN.yaml`** (2530 lines) — 58 instances (52 active + 6 `excluded_because` stubs) across all nine taxonomy sections: entities (defaults, immutability, computed-field input-ignored, required fields, not-found), state machines (terminal lockdowns, promotion expiry sweep boundary at exact `offer_expires_at`), calculations (913-day presence boundary, age-55 exemption, 730-day training window, civics-floor compound gate, 7777 bp truncation, FULL/NONE fee variants, RFE deadline exact-day), validations (401/403/404 ordering, TIER_INELIGIBLE, docs count, readiness gate, SoD, referential mismatch), endpoints (all duplicate-active guards, completion lock, ceremony full/double-assign, stage jumps), RBAC (5 denial + 1 positive ownership instance), cross-cutting (4 OCC stale-version tests, pagination), consistency (immediate computed fields).

## Verification performed
- `scaffold_lint.py` verdict: **clean lint** (1007 calls scanned across both design files; all FK reverse-reachability checks pass). Final verdict block:
  ```
  Coverage
    §1.5 endpoints declared:    69
    §1.1 entities declared:     15
    §1.8 instances scanned:     20
    §1.9 instances scanned:     58
    Calls scanned (§1.8+§1.9):  1007
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```
- All formula-derived assert literals executed in Python and verified (fee tiers, 43752 filing fee, 80/94 readiness scores, 43751 anti-pattern, RFE deadline 2026-10-29, screening expiry 2027-01-28, 730-day window arithmetic).
- Programmatic audits: zero unbound `${var}` placeholders, zero duplicate capture names, zero dangling `excluded_because` refs, zero unresolved `grounds:`, zero forbidden concurrency vocabulary, zero name collisions across the union of both design files, all endpoint roles ⊆ RBAC roles.
- Design-time fixes applied during authoring: promotion-expiry semantics changed from re-queue to terminal auto-decline (prevents infinite re-promotion of the same waitlist head), `ERR_ALREADY_ASSIGNED` removed as unreachable (stage guard fires first), ERR_INVALID_REQUEST moved to priority 1, three sub-resource GET templates renamed to `{id}` parent placeholder for the lint's FK check, pagination captures kept as prose asserts (envelope fields aren't entity fields).

## Step 3: Copy shared files — 2026-08-12T22:32:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1314_citizenship_class_naturalization/workspace/INSTRUCTION.md` (bash-only step).

## Step 4: Generate PRD — 2026-08-12T22:52:00.000Z

PRD generation complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1314_citizenship_class_naturalization/workspace/PRD.md` (356 lines), ending at §5 with no audit footer. The withheld difficulty/corner index files were never opened.

**Document design:** §1 is a 2-paragraph introduction (program mission → system scope). §2 has 9 subsections: RBAC (with per-role identity translation), the verbatim §2.2 envelope block, pagination, common resource properties (including the `common_fields: false` exception for AttendanceRecord/TrainingCredit), the logical clock + three sweeps, integer-cents money discipline, the four OCC rules, left-to-right nested retrieval, and a 17-step ordered guard pipeline covering the full validation priority list. §3 has 9 domain-grouped subsections (program config, screening, readiness+mocks, instruction/attendance, volunteers/accreditation, workshops, fee waivers, packets/filing, cases/RFE/oath). §4 is a 69-row 4-column endpoint table; §5 is a 37-row 2-column error table.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + named outputs: 120 required, 120 present, 0 missing
  (two initial misses — accreditation_level, enrollment_id — were repaired and re-verified)
Status: PASS

Rule coverage check:
- validations[] priority: 17 ordered tiers expressed as an explicit numbered pipeline, 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (endpoint + expected_<parent>_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed (from/to states, preconditions + error ids, side effects incl. cascades), 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose (incl. pinned filing-fee order 38000+4251+1501=43752 vs. rejected 43751, readiness attained/projected variants, 730-day inclusive window, strict deadline/midterm/offer boundaries), 0 missing
- validations[] conditions: 17 checked, 17 matchable to error ids in §2.9/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 69 checked, 69 expressed, 0 missing
- entities[].fields[] structured content (defaults, nullable, enum ranges): verified reconstructible (program defaults, append-only exceptions, null-until-scored rubric fields, etc.), 0 missing
- sibling-branch symmetry: 8 groups checked (GENERAL/LEGAL lapse pair, LAPSED renewal pair, decide APPROVED/DENIED, attained/projected, FULL/PARTIAL/NONE fee variants, advance chain, RFE transitions, seat/workshop cancel paths), all with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 588
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot-verification: all 59 enum/state values present as exact backtick strings; zero fuzzy-word or operator-syntax leaks; all 37 error ids mentioned in §2/§3 prose (not just the §5 table); §4 role columns match the scaffold's `roles[]` exactly for all 69 endpoints; §2.2 emitted byte-verbatim from `section-2.2-response-structure.md`.

## Step 5: Generate unit tests — 2026-08-12T23:12:00.000Z

Generation complete for task_1314_citizenship_class_naturalization.

## What was produced

**`test_helpers/`** (Stage 1) — all under `/home/ubuntu/github/CodingPRD/tasks/task_1314_citizenship_class_naturalization/test_helpers/`:
- `types.py` — 15 entity TypedDicts + 16 status/role enums; `AttendanceRecord` and `TrainingCredit` correctly modeled as append-only (no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with 73 endpoint methods covering the full PRD §4 index
- `api_errors.py` — all 38 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions, `assert_seat_ledger_invariants` (pinned `seats_open = capacity − enrolled − pending`), `assert_same_instant` (tolerant ISO-8601 instant comparison for offer/deadline/expiry timestamps)
- `factories.py`, `constants.py` (Program defaults, 87502/43752 fee constants, stage order), `test_users.py` (opaque shared constants for ProgramAdmin/IntakeCoordinator; mandatory `make_volunteer_headers`/`make_applicant_headers` builders for the entity-backed roles)
- `fixtures.py` — composite setups: screened applicants (ELIGIBLE, readiness 80), GENERAL/LEGAL volunteers, section-with-waitlist, completed enrollment, workshop seat reservation/completion, full packet pipeline (`setup_packet_pipeline` → certified → filed → oath-ready → two-oath-ready-cases), fee waiver lifecycle

**`test_suite/`** (Stage 2) — `conftest.py` + 12 files, **97 tests**, organized by concern (program config, screening, readiness/mocks, seat ledger, attendance, accreditation, workshops, fee waivers, packets, cases/RFE/oath, RBAC, OCC/pagination).

## Audit results
- All 20 difficulty instances have exactly 2 tests; 57 of 58 non-stub corner instances have 1 — every test's docstring ends with exactly one verbatim-resolving `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line
- All 7 corner stubs correctly left untranslated; their `difficulty_instance` cross-references all resolve
- All 151 PRD citation segments verified verbatim against PRD.md via normalized substring match
- No `skip`/`skipif`/`xfail` marks; no scaffold references in comments; all files byte-compile, import, and collect under pytest

## The one intentional gap
`Corner/entities/enrollment_computed_attendance_bp_input_ignored` was skipped per the PRD-first two-condition filter: it asserts a caller-supplied `attendance_bp` is silently ignored, but the PRD never states how undeclared payload fields are handled — a strict-schema implementer would reject the create with `ERR_INVALID_REQUEST` while a lenient one ignores it, so the outcome is not uniquely derivable. Not weakened, not marked — left as a gap per spec.

## Step 6: Generate implementation — 2026-08-12T23:12:00.000Z

Implementation complete. Final report:

## What was built

A complete Python + Flask implementation of the Citizenship Naturalization API at `/home/ubuntu/github/CodingPRD/tasks/task_1314_citizenship_class_naturalization/workspace/implementation/`:

- `start.sh` — executable launcher with the guarded dependency install (`python3 -c "import flask"` check before pip) and `exec python3 app.py` in the foreground; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — entry point, blueprint registration, envelope-shaped error handlers
- `db.py` — in-memory store (empty at every boot, no seeding), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), month-addition and timestamp helpers
- `errors.py`, `util.py`, `auth.py` — error catalog, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, `limit`/`offset`/`total_count`/`has_more` in meta for lists), field validators (bool-safe int checks), `X-User-ID`/`X-User-Role` auth
- `services.py` — all calculations (screening outcome cascade, fee-waiver tiers in pure integer cents, per-line round-half-up filing fee, readiness via exact `Fraction` arithmetic with single final round-half-up, attendance basis points truncated, midterm revoke, training 730-day inclusive window), the three clock sweeps (accreditation lapse, RFE overdue, promotion-offer expiry with re-promotion), seat-ledger promotion selector
- `routes_*.py` (10 modules) — all 60+ endpoints with the PRD §2.9 guard pipeline in exact priority order (well-formedness → auth → role → existence → ownership → state → accreditation → SoD → temporal → overlap → referential → uniqueness → RFE gate → thresholds → money/capacity → OCC 412 last)

## Verification

- Two custom smoke suites (happy path + ~40 edge assertions: OCC 412s, promotion expiry re-promotion, midterm boundary 5000-survives/4999-revokes, SoD, SoD-adjacent accreditation errors, fee-tier boundaries, per-line rounding 43752, RFE deadline exact-at-survives, lapse anniversary exact-at-survives, renewal path, RBAC scoping) — all pass
- `prd-bench-local-run --isolation per-test-server`: **96/97 passed, 0 errors** on the moderate-load run. A later run under heavy concurrent load (21 port holders from other agents' harnesses) showed 92/97 with 4 "could not be restarted" setup errors — environmental flake, different tests each time; server boots in ~1s when uncontended.

## Key findings

1. **One test is unpassable as written** (`test_fee_waiver_household_doc_count_and_denied_tier` in `test_suite/test_08_fee_waivers.py`): case 1 (household 3, income 6,000,000 → expects PARTIAL) requires guideline(3) ≥ 3,000,000 while case 2 (household 4, income 6,430,001 → expects DENIED) requires guideline(4) ≤ 3,215,000 — no monotone linear formula satisfies both. The PRD ("household size **minus one**"), SCAFFOLD.yaml's `fee_waiver_tier` formula, and `SCAFFOLD_DIFFICULTY_DESIGN.yaml`'s own recipe ("guideline 3215000" for household 4, income 4822500 exactly FULL) all confirm `base + per_additional*(size-1)`, which is what I implemented. Case 1's assertion is a test-generator bug.

2. **Harness invocation convention**: the runner's pytest plugin restarts the server with `cwd=test_suite/`, so `--start-command` must use an absolute `cd` form: `--start-command "cd <abs>/workspace/implementation && bash start.sh"`. A bare `bash workspace/implementation/start.sh` resolves against the wrong directory in the per-test restart path and hangs every setup.

3. **Completion decrements `enrolled_count`**: the scaffold's empty `side_effects` for `ENROLLED→COMPLETED` was misleading; the PRD's seat-ledger invariant ("`enrolled_count` equals the true count of `ENROLLED` rows at all times") and the suite (`test_withdraw_completed_enrollment_rejected` asserts `enrolled_count == 0` after completion) require the decrement. Completion is not a promotion trigger (PRD's trigger list is exhaustive: withdrawal, midterm revocation, offer expiry).

## Step 7: Run tests and iterate — 2026-08-13T00:05:00.000Z

**Summary**

- **Iterations run**: 2 (sweep 1 = baseline diagnosis; sweep 2 = verification after fix). Final sweep: all 8 rounds passed 97/97.

- **Tests deleted**: none. The known-failing `test_fee_waiver_household_doc_count_and_denied_tier` survived the STEP 1 audit — PRD §3.7 verbatim-covers both the poverty-guideline formula ("`poverty_base_cents` plus `poverty_per_additional_cents` multiplied by the household size minus one") and the PARTIAL/DENIED branches, and uniquely determines the outcome. The defect was in the test's arithmetic, not in coverage.

- **Fixes applied to `test_suite/`** (assertion mis-translates PRD — STEP 2 "TEST IS WRONG"):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1314_citizenship_class_naturalization/test_suite/test_08_fee_waivers.py`, `TestTierFormulaInteraction::test_fee_waiver_household_doc_count_and_denied_tier`: case 1 (household=3) used income 6,000,000 with the household-4 guideline (3,215,000) miscopied into the comment; under the PRD formula guideline(3) = 2,665,000, PARTIAL cap = 5,330,000, so 6,000,000 computes to DENIED — every PRD-faithful implementation must fail the old assertion. Changed case 1 income to 4,500,000 (strictly between the FULL cap 3,997,500 and PARTIAL cap 5,330,000 for household 3), preserving the test's original two-branch coverage (PARTIAL with doc count 4; DENIED one cent over the 200% cap with doc count 5).

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful throughout.

- **Infrastructure flakes observed (not bugs, no code changed)**: sweep 1 showed transient `Failed: API server ... could not be restarted` setup errors and two `ConnectionResetError(104)` mid-test failures across rounds 1/2/3/7/8 under 8-way parallel load (776 Flask server spawns; root cause is the runner's per-test `kill -9` + respawn racing urllib3 keep-alive connection reuse and boot latency under load). These did not recur in sweep 2; no test or implementation edits were made for them.

## Step 8: Finalize PRD — 2026-08-13T00:20:00.000Z

All verification complete. `PRD_FINALIZED.md` is in place as a byte-identical copy of `PRD.md` — zero edits were warranted.

## Exit Summary

**Line counts / delta**: `PRD.md` 356 lines, `PRD_FINALIZED.md` 356 lines, 0.0% delta (md5-identical: `03d81cac...`).

**Changes made**: none.

**Rationale** — The `<step_7_diff>` contains exactly one fix item, and it is a pure test-fixture arithmetic bug, not a PRD silence or PRD/impl mismatch:

- `test_suite/test_08_fee_waivers.py::test_fee_waiver_household_doc_count_and_denied_tier` had household-4 guideline figures miscopied into a household-3 case. PRD §3.7 already pins the formula verbatim and uniquely ("`poverty_base_cents` plus `poverty_per_additional_cents` multiplied by the household size minus one"; income×100 vs. guideline×`full_waiver_threshold_pct`/`partial_waiver_threshold_pct`; inclusive integer boundaries; `required_document_count` = 2 benefit-based, else household+1). I recomputed the formula independently: household 3 / income 4,500,000 → PARTIAL with 4 docs (matches the fixed test), household 3 / income 6,000,000 → DENIED (proving the old assertion was unpassable by any PRD-faithful implementation), household 4 / 6,430,001 → DENIED with 5 docs, and the 150% boundary cases. The implementation is PRD-faithful throughout, so no PRD wording change traces to this fix.

**Per-edit pre-edit search log** (zero edits committed; the mandatory enumeration for the single candidate edit subject is recorded here):

- (a) **Subject considered**: fee-waiver tier formula, poverty-guideline computation, `required_document_count`, and PARTIAL/DENIED branch behavior — the subject of the one Step 7 fix.
- (b) **Impl paths enumerated and read**: `implementation/services.py:285-294` (`fee_waiver_tier`), `services.py:297-298` (`required_document_count`), `services.py:301-309` (`filing_fee_cents` — FULL→0, PARTIAL→per-line round-half-up then sum, no-tier→raw sum), `routes_feewaivers.py` in full (create:44-53, submit:81-97, decide:100-125, resubmit:128-145), `routes_packets.py:169-178` (certification pricing: DENIED waiver counts as no tier), plus a repo-wide grep for `fee_waiver_tier|required_document_count|final_tier|provisional_tier` across all impl `.py` files to confirm no other callsites exist. Cross-checked against PRD §3.7 (lines 206-214), §3.8's pinned pricing paragraph (line 224, including the 43752-vs-43751 worked example), and the parameter defaults (line 142).
- (c) **Wording adjustment**: none — every enumerated path is covered verbatim by existing PRD prose, so no edit was committed; the no-new-mismatch rule is satisfied vacuously.

## Step 9: Complete PRD — 2026-08-13T00:40:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1314_citizenship_class_naturalization/workspace/PRD_COMPLETED.md` written (copied from PRD_FINALIZED.md, then edited; PRD_FINALIZED.md untouched).

**Size**: PRD_FINALIZED.md 356 lines / 59,024 chars → PRD_COMPLETED.md 361 lines / 63,157 chars (+5 lines, +4,133 chars).

**Counts**: 32 ambiguity-pins, 2 mismatch-revisions (20 edit operations, several bundling related pins).

**Changes** (section — insert/revise — class — what — impl source):

- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as stamped from the logical clock, not wall time — implementation/util.py:12, db.py:43-48
- §2.2 — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404); unexpected failure → `ERR_INTERNAL` (500) in the same envelope — implementation/app.py:36-51
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit`, negative/non-integer `offset` → `ERR_INVALID_REQUEST` — implementation/util.py:141-160
- §2.3 — revise — ambiguity — `created_at` sort ties break by insertion order — implementation/util.py:163-165
- §2.3 — revise — ambiguity — `has_more` true iff `offset` + returned items < `total_count` — implementation/util.py:26
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — implementation/db.py:127-133
- §2.4 — revise — ambiguity — `created_at`/`updated_at` record the logical-clock reading — implementation/db.py:130-131,143-146
- §2.4 — insert — ambiguity — client-supplied timestamps (`scheduled_start`, `ceremony_date`, `earned_at`) stored and echoed verbatim — implementation/services.py:143,158,168,239,254; routes_program.py:57-59
- §2.5 — revise — ambiguity — clock set accepts any instant (no monotonicity enforced) and echoes the supplied string verbatim as `current_utc` — implementation/routes_program.py:50-59
- §2.5 — revise — ambiguity — accreditation anniversary uses calendar-month addition clamping day-of-month to target month's last day — implementation/db.py:84-95
- §2.9 tier 1 — revise — mismatch — `session_index` > `total_sessions` is checked only after the parent section resolves, so existence/ownership failures mask it (contra strict 400-first reading) — implementation/routes_classes.py:257-263
- §2.9 tier 1 — insert — ambiguity — empty body parses as `{}`; malformed/non-object JSON → `ERR_INVALID_REQUEST` — implementation/util.py:41-49
- §2.9 tier 6 — revise — ambiguity — pipeline now places `ERR_INVALID_STAGE_JUMP`, `ERR_CASE_NOT_OATH_READY`, `ERR_COMPLETION_LOCKED` immediately after the `ERR_INVALID_STATE` check — implementation/routes_cases.py:71-76, routes_ceremonies.py:53-57, routes_workshops.py:123-129
- §2.9 tier 10 — revise — ambiguity — `ERR_SCREENING_NOT_ELIGIBLE` evaluated first within the temporal-guard tier, before expiry — implementation/services.py:398-409
- §3.1 — revise — ambiguity — Program overrides must be non-negative integers — implementation/routes_program.py:28
- §3.1 — insert — ambiguity — declared defaults govern until a Program exists; reading config before creation → `ERR_NOT_FOUND` — implementation/db.py:121-124, routes_program.py:45-46
- §3.2 — revise — ambiguity — `date_of_birth` is an ISO 8601 calendar date — implementation/util.py:127-136
- §3.2 — insert — ambiguity — `lpr_months`/`continuous_residence_months`/`physical_presence_days`/`age_years` must be non-negative integers — implementation/routes_applicants.py:73-76
- §3.3 — revise — ambiguity — invalid readiness `variant` → `ERR_INVALID_REQUEST` — implementation/routes_applicants.py:123-125
- §3.3 — insert — ambiguity — `english_points`/`civics_points` rendered rounded half up individually while `score` uses exact unrounded figures — implementation/services.py:355-366
- §3.4 — revise — ambiguity — `start_minute`/`end_minute` are non-negative minutes — implementation/routes_classes.py:42-43
- §3.4 — revise — ambiguity — attendance append does not consult enrollment status; index above `total_sessions` → `ERR_INVALID_REQUEST` — implementation/routes_classes.py:250-263
- §3.4 — revise — ambiguity — completion decrements `enrolled_count` but does not trigger waitlist promotion — implementation/routes_classes.py:237-245
- §3.5 — revise — ambiguity — accreditation accepted only from exact source level (LAPSED must renew); `target_level` outside GENERAL/LEGAL → `ERR_INVALID_REQUEST` — implementation/routes_volunteers.py:81-100
- §3.6 — revise — ambiguity — seat reservation does not consult the workshop's status — implementation/routes_workshops.py:164-187
- §3.6 — revise — ambiguity — completion moves the workshop itself to `COMPLETED` — implementation/routes_workshops.py:112
- §3.6 — revise — ambiguity — reversal requires `COMPLETED` status (`ERR_INVALID_STATE` otherwise) — implementation/routes_workshops.py:123-124
- §3.7 — revise — ambiguity — a `DENIED` decision retains the supplied documented values — implementation/routes_feewaivers.py:115-123
- §3.7 — revise — ambiguity — resubmission leaves `decided_by` untouched — implementation/routes_feewaivers.py:137-144
- §3.8 — revise — ambiguity — `receipt_number` pinned as `NRC-` + six-digit zero-padded sequence starting at `000001` — implementation/db.py:60-62
- §3.9 — revise — ambiguity — `ceremony_date` is a full ISO 8601 timestamp compared against the clock as a date-time — implementation/routes_ceremonies.py:23,81
- §3.9 — revise — ambiguity — assignment response returns the updated case — implementation/routes_ceremonies.py:70
- §5 — revise — mismatch — catalogue claimed to list every error identifier but impl emits `ERR_INTERNAL`; added the `ERR_INTERNAL` | 500 row plus a trigger note — implementation/app.py:48-51

All other implementation behaviors (eligibility cascade, readiness variants, filing-fee order, seat ledger, promotion sweep, RFE lifecycle, ceremony cascades, RBAC scoping, OCC placement, response envelopes) were already uniquely pinned by the PRD and match the implementation as-is; no changes were needed there.
