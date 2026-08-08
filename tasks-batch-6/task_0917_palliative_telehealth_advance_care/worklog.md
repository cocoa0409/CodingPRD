# Worklog — task_0917_palliative_telehealth_advance_care

Scenario (verbatim from user):
`917. Palliative Telehealth & Advance-Care Planning: referral & goals-of-care, symptom assessment & plan, advance-directive & POLST completion, interdisciplinary & family meeting, medication & DME, hospice-transition, after-hours support, documentation`

Difficulty target: **beyond-Expert** (user asked for "hard than expert level").

## Step 1: Create task directory — 2026-08-03T17:26:30.587Z

Created `tasks/task_0917_palliative_telehealth_advance_care/` and `tasks/task_0917_palliative_telehealth_advance_care/workspace/`. Index 0917 = highest existing (0916) + 1.

## Step 2: Generate scaffold — 2026-08-03T18:30:00.000Z

All three artifacts are written, parse cleanly, and pass the skill's own linter.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_0917_palliative_telehealth_advance_care/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0917_palliative_telehealth_advance_care/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0917_palliative_telehealth_advance_care/SCAFFOLD_CORNER_DESIGN.yaml`

## Structural summary (vs. calibration target)

| Dimension | Target | Delivered |
|---|---|---|
| Entities | 13–15 | **14** |
| Endpoints | 55–65 | **65** (42 write, 23 read) |
| Error codes | 26–32 | **32** |
| State machines | 9+, ≥4 non-linear | **13**, **12 non-linear** |
| Calculations | 9+, ≥4 dual-variant | **16**, **5 dual-variant** |
| Validation ladder | ≥14 rungs | **31 rungs** |
| OCC rules | ≥2 distinct entities | **3** — Patient, CarePlan, HospiceElection |
| Conservation invariants | ≥2 | **3** — DME units, patient MME ledger, ACP minutes |
| Deepest cascade | ≥4 | **5** (death event: freeze → election → med orders → care plan → assessment → escalation); plus two depth-4 chains (document supersession, capacity determination) |

Declared constants: **76** top-level (plus per-calculation restatements). **Zero undeclared** — an ALL-CAPS token sweep left 7 residuals, all verified as enum members or the fixed `ERR_XXX` envelope placeholder, and I patched 6 endpoint descriptions so every request-body enum's member set is now stated explicitly.

## Reachability self-repairs

1. **Execute from-state widening (real fix).** `POST /advance-care-documents/{id}/execute` originally required `PENDING_EXECUTION`, which permanently masked rungs 12 (`ERR_EXECUTION_REQUIREMENT_UNMET`) and 13 (`ERR_SIGNATURE_INCOMPLETE`) — a document failing those checks is by definition still `DRAFT`. Rung 7 now admits `{DRAFT, PENDING_EXECUTION}`. Three sibling widenings are declared for the same reason (refills → rung 22, DME fulfillment → rung 24, conference attestations → rung 18).
2. **Capacity-cascade predicate made checkable.** Hop 3 keyed off `attesting_party_user_id == the surrogate's person_user_id`, unresolvable because `Caregiver` is `entity_backed:SurrogateDesignation` (X-User-ID is the designation id, not the person id). Re-keyed to `surrogate_stated == true`.
3. **`SurrogateDesignation.INVALIDATED` deleted** — a dead enum value no transition produced.
4. **Hospice period counter** — `CERTIFIED→ELECTED` said "becomes 1"; changed to increment, otherwise the revoke/re-elect cycle would silently reset the benefit-period arithmetic.
5. **`DmeOrder.PENDING_AUTH` documented as an alternate initial state** — it is selected at creation from the inventory item's flag, not entered from `REQUESTED`; a graph walk flagged it as unreachable until this was made explicit.

Verified mechanically: all 12 status-graph machines have zero unreachable states, and **all 32 error codes are asserted as an actual outcome** (not merely cited in `grounds`) somewhere across the two design files.

## Design-file instance counts

- **§1.8**: 9 rule blocks × 2 = **18 instances**, all non-stub.
- **§1.9**: **55 instances across 8 sections — 50 non-stub + 5 `excluded_because` stubs** (entities 8, state_machines 10, calculations 9, validations 18, endpoints 3, rbac 3, cross-cutting layers 3, consistency 1). All 5 stubs cite a difficulty instance that exists by name; no duplicate names across the union.

Every formula-derived assertion is a literal computed by running the scaffold's own formulas in Python — including the mode-(b) rounding-order case (round-per-order-then-sum gives 9.9 mg where sum-then-round gives 9.8) and the mode-(c) evaluation-order case (the annual cap drops the allowed amount to 7380, flipping the coinsurance tier to 0.1 for a net of 6642, where reading the tier off the uncapped 13685 would give 0.2).

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  665

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two notes for the caller: the lint ran clean on its first invocation (no fix-and-rerun loop was needed), and `SCAFFOLD.yaml` contains neither design key. I did not read any sibling task directory.

**Orchestrator independent verification:** all three files `yaml.safe_load` clean; SCAFFOLD.yaml top-level counts confirmed (14 entities / 65 endpoints / 13 state machines / 16 calculations / 32 errors / 76 declared constants); independent ALL_CAPS sweep left 57 residual tokens, every one an enum member, status name, reason code, drug name, or jurisdiction code — zero undeclared numeric constants; neither design key present in SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-08-03T18:31:21.729Z

`cp ./INSTRUCTION.md ./tasks/task_0917_palliative_telehealth_advance_care/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-03T18:47:57.832Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0917_palliative_telehealth_advance_care/workspace/PRD.md` — 467 lines, written in 8 bounded increments and re-read end-to-end after assembly. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, and all sibling task directories were never opened.

## Section list

- **1. Introduction** (3 paragraphs — documentation-burden framing, mount point, plus the two pervasive properties: ordered rejection, three conserved quantities)
- **2. Global Specifications** — 2.1 Care Team Identity and RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination and List Filtering · 2.4 Common Record Properties, the Logical Clock and Timestamp Rendering · 2.5 The Rejection Ladder (all 31 rungs, ordered) · 2.6 The Records Freeze · 2.7 Stale-Version Guards on Three Parent Records · 2.8 Arithmetic, Precision and Rounding · 2.9 Three Conserved Ledgers · 2.10 Cascades and Hierarchical Consistency · 2.11 Segregation of Duties · 2.12 Nested Path Resolution
- **3. Business Logic & Workflows** — 3.1 Registration and Referral Triage · 3.2 Who May Decide: Surrogate Designations and Capacity · 3.3 Advance Care Documents · 3.4 Goals of Care: The Code-Status Ladder · 3.5 Care Plans and Symptom Surveillance · 3.6 After-Hours: Escalation Tiers · 3.7 Interdisciplinary and Family Conferences · 3.8 Analgesia: Opioid Orders and the Patient MME Ledger · 3.9 Durable Medical Equipment · 3.10 Hospice Election, Certification and Benefit Periods · 3.11 Advance-Care-Planning Billing · 3.12 Death, the Records Freeze and Program Closure
- **4. Endpoint Definitions** (4-column table) · **5. Error Code Catalogue** (2-column table). Document ends at §5 — no audit footer.

## Completeness self-check vs SCAFFOLD.yaml

| Item | Scaffold | In PRD |
|---|---|---|
| Endpoints | 65 | 65 |
| Error codes | 32 | 32 (all also named in §1–§3 narrative, not just the §5 table) |
| State machines | 13 | 13 (every state name of every machine present verbatim) |
| Calculations | 16 | 16 (each with formula, variants, constants, rounding point, evaluation order) |
| Constants | 76 | 76 (numeric value present in prose, verified by pattern match) |
| Validation rungs | 31 | 31, ordered, each with error id + HTTP status + scope |
| OCC rules | 3 | 3 (endpoint + `expected_*_version` + error id + 412 each) |
| Conservation invariants | 3 | 3 |
| Entity field names | 136 | 136, 0 missing |
| Request-body identifiers | 92 | 92, 0 missing |
| Query params | 14 | 14, 0 missing |
| Enum members / role names | 113 / 10 | 0 missing |

Hard contracts: **Contract 1 PASS** (0 missing across fields/body/query), **Contract 2 PASS** (ladder ordering, 3 OCC rules, all transitions with preconditions+side effects, all 16 calculations, all `applies_to` scopes, sibling-branch symmetry on the 5 dual-variant calcs), **Contract 3 PASS** (1,002 backtick tokens scanned in §3; 0 path-leading, 0 bare-method, 0 method+path; §3 contains zero occurrences of `/palliative` or `_clock`).

Notable transcription judgements worth flagging to the pipeline: (a) the scaffold's `CONFLICT_HOLD → ATTESTED` leg increments `attestation_count` to 2 while `ATTESTED → EFFECTIVE` requires `attestation_count == 1` — I transcribed both literally rather than reconciling them, since inventing a reconciliation would diverge from the test-generation source; (b) three constraint failures have no dedicated error code in the catalog (duplicate `mrn`, conference attestation by a discipline not in `disciplines_present`, `DISPOSITION` naming the system-reserved `ADMINISTRATIVE_CLOSE`) — each is stated as `ERR_VALIDATION` under rung 4, the only rung covering body constraints; (c) `resolution_reason` on RESOLVE is phrased as `ESCALATION_DISPOSITIONED` when the escalation axis is `DISPOSITIONED` and `SYMPTOM_CONTROLLED` otherwise, which covers the scaffold's two declared cases plus the undeclared `ESCALATED` case without inventing a third value.

**Orchestrator note:** PRD.md is 466 lines / 32 headings on disk. Doc-generator flag (a) — the `CONFLICT_HOLD → ATTESTED` / `ATTESTED → EFFECTIVE` `attestation_count` tension — is carried forward to Step 7 as a *friction point to inspect first*, not a pre-judged verdict.

## Step 5: Generate unit tests — 2026-08-03T19:19:50.277Z

Test infrastructure and suite are complete and audited.

## Files written

**`test_helpers/`** (2,337 lines, 9 modules)
- `constants.py` — every PRD threshold (rate variants, MME factors, ladder ranks, period lengths, tier deadlines) plus a table of **deliberately distinct** operator identities so no segregation-of-duties rule is silently self-satisfied (`u_attending_1` ≠ `u_witness_*` ≠ `u_spouse_1`; `u_physician_1` ≠ `u_nurse_1` ≠ `u_physician_2` ≠ `u_hospice_md_1`).
- `types.py`, `api_errors.py` (32 errors + status map registered with the framework), `api_client.py` (all 65 endpoints), `factories.py`, `test_users.py` (opaque-role constants + `make_caregiver_headers(designation_id)` for the one `entity_backed` role), `assertions.py`, `fixtures.py` (5 tiers, all state built through declared endpoints), `__init__.py`.
- **Timestamps are compared semantically everywhere**: `parse_instant()` / `assert_same_instant()` / `assert_instant_equals_offset()`. No test string-compares a datetime.

**`test_suite/`** — `conftest.py` + 13 domain-named test files, **86 tests**.

## Self-check numbers

| Check | Result |
|---|---|
| `def test_` count vs `Design:` tag lines | **86 == 86**, 1:1, none untagged, none dual-tagged |
| `pytest.mark.skip` / `xfail` / `skipif` anywhere in tree | **0** |
| Every `Design:` tag resolves to a real `name:` in the cited yaml | **86/86** |
| Every test body carries an assertion construct | **86/86** |
| Verbatim PRD-citation check (every ≥8-word quoted string grep'd against PRD.md after whitespace normalisation) | **all pass** |
| pytest collection | **86 collected, 0 errors** |
| pyflakes over both trees | clean |
| "scaffold"/§1.x/Table-N leakage in generated code | none |

**Queue A (difficulty):** 18/18 non-stub instances covered, **exactly 2 tests each = 36 tests**. No shortfalls.
**Queue B (corner):** 50/50 non-stub instances covered, 1 test each = 50 tests. **No instances skipped.** All 5 `excluded_because:` stubs verified to cross-reference a real difficulty instance; none translated.

## On the friction point you flagged

The `CONFLICT_HOLD → ATTESTED` leg does raise `attestation_count` to 2 while `ATTESTED → EFFECTIVE` requires `attestation_count == 1`, so an order that passes through `CONFLICT_HOLD` can never become `EFFECTIVE`. **This is not a derivability gap and blocked no instance.** The only instance traversing that pair — `Corner/validations/conflict_hold_attestation_without_a_note_returns_goals_conflict` — stops at `ATTESTED` and asserts `Patient.code_status` is still `FULL_CODE`, which is exactly what the PRD's own arithmetic produces. PRD §3.4 pins both legs unambiguously, so the test was generated as designed. It's a dead-end path in the state machine, not an ambiguity.

## One assertion dropped (reported for doc-generator feedback)

In `Corner/cross_cutting_complexity_layers/occ_stale_patient_version_rejects_the_second_document_execution` I omitted the design's incidental assertion `Patient.code_status == FULL_CODE`. PRD §2.10's document cascade phrases hop 3 as *"because that order was superseded, the patient's `code_status` becomes…"* (chain-conditional), while §3.3 line 223 restates the cascade as a flat list, so a faithful PRD-only reader could reasonably rewrite `code_status` on every execution regardless of whether hop 2 fired. The instance's core OCC claim (412 + `ERR_STALE_PATIENT_VERSION`, retry succeeds, predecessor `SUPERSEDED`) is fully asserted. **Suggested PRD fix:** state explicitly whether hop 3 fires when `supersedes_document_id` is null, the way the death cascade already does for its own chain break ("hop 1 has nothing to close and hop 2 is triggered directly by the freeze").

Two additional low-confidence spots worth knowing about, both kept because no other catalogue error fits: the *early* escalation promotion and the care-plan-activation-on-a-`REFERRED`-patient failures are asserted as `ERR_INVALID_STATE`, which PRD names for the sibling condition on the same transition but not for these two conditions directly.

## Step 6: Generate implementation — 2026-08-03T19:19:50.277Z

Implementation complete and verified.

## Files written (2,914 lines total)

`.../workspace/implementation/`
- `app.py` (65) — blueprint registration, envelope error handlers, `0.0.0.0:$PORT` boot
- `config.py` (163) — 76 declared constants, enums, ranks
- `errors.py` (117) — 32-entry error catalogue + HTTP status map
- `store.py` (145) — logical clock, in-memory dicts (empty at boot), the single datetime renderer
- `envelope.py` (73) — `meta`/`response_type`/`data` envelope, pagination meta, serialisation
- `ladder.py` (269) — the 31-rung ladder primitives + `touch()` + pagination/filters
- `calc.py` (163) — the 16 calculations, all `ROUND_HALF_UP`, money in whole-cent ints
- `cascades.py` (253) — 3 conserved ledgers, authority selector, 4 cascades
- `routes/`: `patients.py` (244), `documents.py` (293), `careplans.py` (286), `conferences.py` (171), `medications.py` (156), `dme.py` (162), `hospice.py` (170), `claims.py` (156), `clock.py` (19)
- `start.sh` (8, guarded pip install, `exec python3 app.py`), `requirements.txt`

## url_map gate: MISSING 0 / EXTRA 0 (65 declared = 65 implemented)

## Adjudications

**Timestamps.** Every instant is held internally as an aware UTC `datetime`; a single `fmt_dt()` in `store.py` is the only render site, emitting `YYYY-MM-DDTHH:MM:SS.mmmZ` uniformly for `created_at`/`updated_at`, echoed caller instants (any valid ISO form re-rendered — offsets converted, fractions preserved/truncated to ms), clock stamps, and derived instants (`response_due_at`, `ack_due_at`, `reattest_due_at`, `next_refill_allowed_at`, `current_period_end`, `attestation_due_at`, `signature_log[].signed_at`). `date_of_birth` is echoed verbatim. `api_request_timestamp` also reads the logical clock (PRD: server never reads wall clock).

**Enum routing.** PRD rung 4 states enum-membership failures use `ERR_VALIDATION` — no enum code exists in the catalogue. Every enum check on every body field (including array members and `ADMINISTRATIVE_CLOSE` on escalation disposition) flows through one helper `_check_enum` → `ERR_VALIDATION` (400). List filter query params are **not** validated (PRD 2.3 declares only `limit`/`offset` bounds a shape failure), so an off-enum filter returns an empty page with `total_count` 0.

## Guardrail 7 resolutions
- **Ladder order**: each route calls primitives strictly ascending 1→31; rung 6 (freeze) precedes every business rung and is skipped only for the 5 exempt writes (dme close, conference attestations, claim attest/submit/adjudicate). The four rung-7 widenings are implemented (refill, DME `SCHEDULED`, conference attestation, document execute) so rungs 12/13/18/22/24 are reachable. Verified rung 14 pre-empts 15, rung 4 pre-empts 5, rung 3 pre-empts 4, freeze pre-empts state.
- **OCC**: three guards, mandatory fields, at rung 8 (`ERR_STALE_PATIENT_VERSION`/`_CARE_PLAN_`/`_ELECTION_`, 412). `touch()` refreshes `updated_at` and increments `version` **at most once per row per request** (request-scoped set), so the patient bumps once even when execution also rewrites `code_status`.
- **Conservation**: all three ledgers are recomputed as exact aggregates rather than incremented — `active_daily_mme` = Σ ACTIVE `mme_daily` (Decimal), `acp_minutes_claimed`/`acp_paid_cents_ytd` from claim status, and inventory `available/reserved/delivered` derived from order status so `total_units` identity holds after all four moves. Round-trips verified to return exactly to prior values.
- **Segregation of duties**: witness ≠ attending / PROPOSED-or-ACTIVE surrogate / any beneficiary (including REVOKED); verifier and MME-reviewer ≠ prescriber; second certifier ≠ attending certifier.
- **Dual-variant calcs**: referral (source→PAYER/CLINICIAN), distress (reporter_type, single final round-half-up then cap), MME (opioid_status; NAIVE scales *before* the 1-dp round), claim (modality rate, then annual cap, then coinsurance read off the **capped** amount), execution readiness (jurisdiction), breakthrough (round-per-order → sum → 15% of sum → convert → round once).
- **Death cascade**: 5 hops in order; hop 4 is scoped to assessments under hop-3-closed plans, hop 5 to escalations naming those assessments; `DELIVERED` DME orders deliberately left open (verified closable post-death with `PICKED_UP_ON_DISCHARGE`). Capacity cascade hops 3–4 fire only if hop 2 invalidated a conference.
- **Lists**: `created_at` ascending with insertion order as a stable tiebreak (the logical clock makes timestamps collide); off-enum filter → empty page; `limit`/`offset` bounds → `ERR_VALIDATION`.

## Guardrail 8 (friction point)
Implemented **literally**: `CONFLICT_HOLD → ATTESTED` sets `attestation_count` to 2, and `ATTESTED → EFFECTIVE` requires `attestation_count == 1` plus a differing role — so an order that passed through `CONFLICT_HOLD` cannot become `EFFECTIVE`. A non-advancing attestation (same role, or count ≠ 1) is accepted (200), stamps the acting `X-User-ID` into the role's field, and leaves status/count unchanged, per "repeating the same role does not advance it" (no error code exists for that case).

Two other unnamed-error judgements, flagged: care-plan activation against a non-enrolled patient and escalation-open against a wrong-axis assessment use `ERR_INVALID_STATE` (rung 7); a benefit period whose `period_start` precedes the outgoing `current_period_end` uses `ERR_VALIDATION`, evaluated after rungs 27/28 as the PRD narrates. Symptom-assessment creation does **not** require an ACTIVE plan (PRD §3.5 states no such rejection and no error code).

Validation: 205 assertions across 4 smoke suites (all pass) plus a live `bash start.sh` boot on `$PORT` bound to `0.0.0.0` serving a fresh, empty store.

**Orchestrator independent verification after Steps 5+6:** `def test_` count 86 == `Design:` tag count 86 (36 Difficulty + 50 Corner); pytest collects 86, 0 errors; zero `skip`/`xfail`/`skipif` in either tree; zero persistence smells (`sqlite|json.dump|pickle|shelve|/tmp`) in `implementation/`; zero test-helper identity strings (`u_attending`, `u_witness`, `u_physician`, …) present anywhere in `implementation/` — no isolation breach despite Step 6 finishing before Step 5. Independent `app.url_map` vs scaffold `endpoints[]` diff: 65 declared = 65 implemented, MISSING 0 / EXTRA 0 (the lone apparent diff was the orchestrator's own prefix-prepend on `/_clock/set_current_utc`, which scaffold, PRD, impl, and tests all agree is deliberately unprefixed). `workspace/sweep.sh` pre-staged (2 waves of 4, no `pkill`, `SWEEP_DONE` marker).

## Step 7: Run tests and iterate — 2026-08-03T19:28:36.549Z

Clean on the first sweep, and verified genuine rather than merely accepted.

## Result: 86/86 across all 8 rounds — no fixes, no deletions

**Iterations run:** 1 (the first 8-round sweep came back clean; no failing-test union existed, so the diagnostic protocol never engaged).

**Tests deleted:** none. No test failed in any round, so no test was ever subject to a STEP 1 coverage / unique-derivability judgement.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Clean-sweep verification (the numbers, not just the aggregate)

| Check | Result |
|---|---|
| 8 `results.N.json` present + parseable | yes, all 8 |
| Individual test rows per round | **86 in every round** (not just an aggregate counter) |
| Sorted test-name set across rounds | **byte-identical, all 8** |
| `def test_` in `test_suite/` vs collected | **86 == 86**; set difference in both directions is empty |
| Per-round runner line | `collected 86 items` … `86/86 passed, 0 failed, 0 errors, 0 skipped` — all 8 |
| `skip` / `xfail` / `skipif` in test tree | **zero grep hits at all** (not even docstring false positives) |
| Persistence smells in `implementation/` (`sqlite\|open(\|json.dump\|pickle\|/tmp\|shelve\|redis\|csv`) | **zero hits** — storage is pure in-memory dicts |
| Non-vacuity | 686 assert/validate statements over 86 tests; per-test duration 0.557–1.143 s (mean 1.033, sum 88.8 s) — zero near-zero durations; `conftest.py` is fixtures only (api client + 10 role-header builders), no monkeypatching, no autouse neutering |
| Structural parity | 65 routes registered == 65 scaffold endpoints |

Both alarming-but-benign log artifacts appeared exactly in their documented forms and are not crashes: one `Killed` immediately after test #1's name (per-test isolation SIGKILLing the pre-boot server), and `143` only ever as a line number in `lifecycle:stop:143`. The single `FAILED`-matching grep hit was the test *name* `test_attesting_a_quorum_failed_conference_names_the_quorum_rule PASSED`.

### Verdicts on the three upstream friction points

**1. `CONFLICT_HOLD → ATTESTED` vs `ATTESTED → EFFECTIVE` — did not surface; resolutions are genuinely compatible.** The upstream read is correct and the dead end is a real PRD property, not a defect. `routes/documents.py:249-275` implements all three PRD 3.4 sentences literally: `DRAFT → CONFLICT_HOLD` sets `attestation_count = 1`; the `CONFLICT_HOLD` branch increments it (to 2) and moves to `ATTESTED`; the `ATTESTED` branch gates on `attestation_count == 1`, so an order that transited `CONFLICT_HOLD` computes `advances = False` and simply stays `ATTESTED`. The matching test (`test_04_code_status_orders.py:184-240`) stops exactly there — it asserts `status == "ATTESTED"`, that the note was stored, and that `code_status` remains `FULL_CODE` (consistent with the order never taking effect). It never asserts the unreachable `EFFECTIVE` transition, so nothing forces the contradiction into the open.

**2. Document-cascade hop-3 conditionality — did not surface; correctly handled by omission.** This is a real unique-derivability seam and both sides stayed on the safe side of it. `cascades.py:153-169` resolves it toward the §3.3 flat reading: hops 1–2 are nested under `if predecessor_id`, but `rewrite_code_status(patient, document["stated_code_status"])` is dedented to the function body and therefore runs unconditionally on every execution. The §2.10 chain-conditional reading would instead have made it fire only when a predecessor was superseded. Test-gen's dropped `Patient.code_status == FULL_CODE` assertion is precisely the assertion that would have discriminated the two readings, so the surviving test (`test_supersession_rewrites_the_patient_code_status_and_parks_in_flight_orders`) exercises only the predecessor-present path, where both readings agree.

**3. The three no-dedicated-code error judgements — (a) and (b) surfaced as agreement; (c) is untested.**
- (a) *Early escalation promotion → `ERR_INVALID_STATE`* — test and impl agree, and the tier-3 ceiling half is actually verbatim in PRD 3.6 ("There is no transition out of tier 3 by promotion, so a fourth attempt is refused with `ERR_INVALID_STATE`"). The early-promotion half rides the same self-loop guard sentence with no dedicated catalogue code, making rung 7 the natural landing spot. Test asserts both at 409.
- (b) *Care-plan activation against a non-enrolled patient → `ERR_INVALID_STATE`* — agree. PRD 3.5 phrases it as a transition requirement ("Activating from `DRAFT → ACTIVE` requires the patient's `program_status` to be `ACTIVE` or `HOSPICE_ELECTED`"), and `routes/careplans.py:52-54` routes it through the same `state()` helper as rung 7. The test asserts 409 `ERR_INVALID_STATE` and the patient is still `REFERRED`. Worth flagging that this one is the softest of the three — the ladder defines rung 7 over "the target row", and here the target row is the care plan while the tested condition is on the *patient* — but test and impl chose identically, so it never became a failure.
- (c) *`period_start` preceding the outgoing `current_period_end` → `ERR_VALIDATION`* — **never surfaced, because no test exercises it.** The impl carries the check (`routes/hospice.py:118-120`), but no test in `test_10_hospice_election_and_benefit_periods.py` asserts the rejection path — consistent with test-gen having declined it on unique-derivability grounds, since PRD 3.10 states the non-overlap requirement without naming any error code.

Artifacts: results and logs are at `.../workspace/implementation/results.{1..8}.json` and `.../workspace/round_logs/round.{1..8}.log`.

**Orchestrator independent verification of the clean sweep:** re-parsed all 8 `results.N.json` myself — each has **86 individual rows**, status distribution `{'passed': 86}`, aggregate `86/86`, and the sorted test-name list is identical to round 1 in all 7 comparisons. AST walk of `test_suite/` finds **86 test functions, 652 assertion constructs, 0 bodies without an assertion**. File mtimes confirm zero post-generation edits: every `implementation/` and `test_suite/` source file predates `results.1.json`, so the "0 fixes" claim is corroborated on disk rather than only in the subagent's report.

## Step 8: Finalize PRD — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised, so there is no `<step_7_diff>` to patch against. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-03T19:46:41.394Z

Done. `PRD_COMPLETED.md` is written.

## Summary

**Files:** `workspace/PRD_COMPLETED.md` (from `PRD.md`)

- Line count: 466 → **470** (+4; two inserted paragraphs, no new headings)
- Char count: 118,507 → **142,103** (**+23,596**)
- 48 lines revised in place, 2 paragraphs inserted
- **Counts: 44 ambiguity-pins, 6 mismatch-revisions**

### Changes

- **2.2** — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-alnum chars; `api_request_timestamp` is a read of the *logical* clock, so it repeats while the clock is still — `envelope.py:16,22`
- **2.3** — insert — ambiguity — non-integer / empty `limit`/`offset` are shape failures — `ladder.py:218-231`
- **2.3** — insert — ambiguity — `created_at` ties are broken by **insertion order**, never by `id` — `store.py:120-126`
- **2.3** — insert — ambiguity — filter values are unvalidated exact string matches: an off-enum filter yields an empty page, not a 400; undeclared query params are ignored — `ladder.py:243-260`
- **2.4** — revise — **mismatch** — `version` increments **at most once per row per request**, not once per write — `ladder.py:201-214`
- **2.4** — insert — ambiguity — derived ledgers/counters re-stamp their row only when the recomputed value actually differs — `cascades.py:28-33`
- **2.4** — insert — ambiguity — creating a child row does **not** write the patient row (exceptions: symptom assessment, equipment request→inventory line) — `routes/*.py` create handlers
- **2.4** — insert — ambiguity — caller-supplied instants (`scheduled_*`, `delivery_window_*`, `service_date`, `period_start`, `face_to_face_at`, `signed_at`, `current_utc`) are re-rendered, never echoed verbatim — `store.py:57-66`, `envelope.py:26-37`
- **2.4** — insert — ambiguity — offsets converted to UTC; no-zone instants read as UTC; date-only read as midnight UTC; sub-ms digits **truncated** not rounded — `store.py:22-66`
- **2.4** — insert — ambiguity — `date_of_birth` checked for shape only, not calendar validity — `store.py:28`, `ladder.py:96-99`
- **2.5 rung 4** — insert — ambiguity — explicit `null` ≡ omitted; undeclared body keys ignored; absent body = `{}`; the three conditionally-required fields (`decline_reason_code`, `disposition`, `denial_reason`) are checked at rung 4, above the freeze — `ladder.py:150-162`, `routes/patients.py:144`, `routes/careplans.py:251`, `routes/claims.py:124`
- **2.5** — insert (new paragraph) — ambiguity — the four rung-less checks and where they sit: plan-activation `program_status` and escalation promotion (both `ERR_INVALID_STATE`, rung 7); conference discipline checks (`ERR_VALIDATION`, *below* rungs 18/19); benefit-period non-overlap (`ERR_VALIDATION`, *below* rung 28) — `routes/careplans.py:53,233-234`, `routes/conferences.py:141-144`, `routes/hospice.py:118`
- **2.6** — insert — ambiguity — on creates the gate reads the body's `patient_id` only; inventory stocking and the clock are ungated — `routes/dme.py:20`, `routes/clock.py:13`
- **2.9** — insert — ambiguity — ledgers are **derived, not incremented**; "moves"/"increases" describe net effect only — `cascades.py:37-97`
- **2.10 death** — revise — **mismatch** — hop 4 scoped to plans *this cascade* closed; `open_symptom_count` is an aggregate, 0 only in the ordinary case — `cascades.py:238-246`
- **2.10 death** — revise — ambiguity — hop 5 scoped to assessments *this cascade* resolved — `cascades.py:247-253`
- **2.10 death** — insert — ambiguity — **no** equipment order is touched in any state; documents, code-status orders, conferences, surrogates, referrals and claims untouched; `breakthrough_dose_mg` not recomputed — `cascades.py:216-253`
- **2.10 doc-exec** — insert — ambiguity — hop 1 fires only on an `EXECUTED` predecessor; hop 2 scoped to the executing patient's orders; **hops 3–4 unconditional** — `cascades.py:153-169`
- **2.10 capacity** — insert — ambiguity — hop 2 gates everything: no invalidated conference ⇒ hops 3/4 and the claims leg do not fire; the code-status revert runs even when no order was superseded; claims leg scoped to the just-invalidated set — `cascades.py:181-212`
- **2.10 capacity** — insert — ambiguity — most-recently-executed tie-break falls through to insertion order — `cascades.py:120-127`
- **2.10 supersession** — insert — ambiguity — revocation revert + parking are unconditional — `cascades.py:172-177`
- **2.11** — insert — ambiguity — rung 21 does **not** apply to the resurrection certification — `routes/hospice.py:61-63`
- **2.11** — insert — ambiguity — a repeated-role attestation is accepted, overwrites the stamp, bumps `version` — `routes/documents.py:263-275`
- **2.12** — insert — ambiguity — body FKs are existence-checked only; cross-patient references are permitted — `ladder.py:172-178`
- **2.12** — insert — ambiguity — unknown path / wrong method ⇒ 404 `ERR_RESOURCE_NOT_FOUND` **before** authentication; trailing slash tolerated — `app.py:32,43-51`
- **3.1** — revise — **mismatch** — registration returns `active_daily_mme` **0.0** (and `deceased_at` null) — `routes/patients.py:37`
- **3.1** — insert — ambiguity — `mrn` whitespace-only rejected; uniqueness is byte-exact — `ladder.py:93-94`, `routes/patients.py:56`
- **3.1** — insert — ambiguity — an `ACCEPT` on an already-`ACTIVE` patient advances the referral but does **not** write the patient — `routes/patients.py:160-162`
- **3.2** — insert — ambiguity — authority selector falls through to insertion order — `cascades.py:104`
- **3.2** — insert — ambiguity — capacity determination has **no** state precondition and is recorded (with a version bump) even when the status is unchanged — `routes/patients.py:72-85`
- **3.3** — insert — ambiguity — revocation revert + parking are unconditional; tie-break insertion order — `cascades.py:172-177`
- **3.4** — insert — ambiguity — `conflict_resolution_note` whitespace-only rejected; stored **only** on the `CONFLICT_HOLD` path — `routes/documents.py:242,257-262`
- **3.4** — insert — ambiguity — recorded role read off the two stamp fields; non-advancing attestations accepted + stamped + version-bumped; the goals-conflict branch leaves `attestation_count` at 2, so such an order can never become `EFFECTIVE` — `routes/documents.py:208-275`
- **3.5** — insert — ambiguity — plan activation `program_status` failure ⇒ `ERR_INVALID_STATE`; the `UNDER_REVISION → ACTIVE` leg has no such requirement — `routes/careplans.py:51-58`
- **3.5** — insert — **mismatch** — assessments may be filed against a plan in **any** status, and the plan need not belong to the patient — `routes/careplans.py:112-113`
- **3.5** — insert — ambiguity — `open_symptom_count` moves write the patient row (version bump); `RESOLVE` closes escalations without overwriting `disposition` — `routes/careplans.py:138,164-169`
- **3.6** — insert — ambiguity — opening an escalation bumps the assessment's version; opens with nulls; records the supplied `patient_id` regardless of the assessment's — `routes/careplans.py:207-221`
- **3.6** — insert — ambiguity — a **premature** promotion is also `ERR_INVALID_STATE`, indistinguishable from the tier ceiling — `routes/careplans.py:232-234`
- **3.7** — insert — ambiguity — creation defaults (`documented_minutes` 0, empty arrays, four nulls) — `routes/conferences.py:47-64`
- **3.7** — insert — ambiguity — `documented_minutes` has no declared range; `disciplines_present` optional on **both** kinds and *omitting* it retains the prior roster; a FAMILY conference held without a roster can never be attested; `decision_maker_id` on an IDT hold is FK-checked then ignored — `routes/conferences.py:74-97`
- **3.7** — insert — ambiguity — a FAMILY hold stamps `held_at`/`attestation_due_at`, leaves `quorum_met` false, and leaves `decision_maker_id` **null** when the server resolved the surrogate itself — `routes/conferences.py:109-119`
- **3.7** — insert — ambiguity — the two discipline `ERR_VALIDATION`s sit below rungs 18/19; `attested_disciplines` is in attestation order — `routes/conferences.py:138-147`
- **3.8** — insert — ambiguity — order opens with four nulls; `dose_amount` echoed **exactly as supplied**, not normalised — `routes/medications.py:44`
- **3.8** — insert — ambiguity — the attestation's from-state is selected by `attestation_type` at rung 7, above segregation — `routes/medications.py:83-88`
- **3.8** — insert — ambiguity — the `REVIEW_REQUIRED` branch leaves fill timestamps null and does not write the patient — `routes/medications.py:96-97`
- **3.8** — revise — **mismatch** — `breakthrough_dose_mg` is written back **only onto currently-`ACTIVE` orders**; an order that left `ACTIVE` keeps its stale value — `cascades.py:45-54`
- **3.9** — insert — ambiguity — order creation re-stamps the inventory line; `SCHEDULED` moves no units so the line is **not** written; delivery/close re-stamp it; the compared window is the order's stored one — `routes/dme.py:78,104-126,145`
- **3.9** — insert — ambiguity — the close's from-state is selected by `closed_reason` — `routes/dme.py:138-141`
- **3.10** — insert — ambiguity — certification admits `PENDING_CERT`(<2) or `REVOKED` only — `routes/hospice.py:57-59`
- **3.10** — insert — ambiguity — periods admit `CERTIFIED`/`ELECTED`; `face_to_face_at` stored whenever supplied and retained when omitted; non-overlap failure is `ERR_VALIDATION` below the face-to-face rung — `routes/hospice.py:107,115-128`
- **3.10** — insert — ambiguity — period 1 sets `HOSPICE_ELECTED` with no patient precondition; periods 2+ do **not** write the patient — `routes/hospice.py:129-135`
- **3.10** — insert — ambiguity — revocation sets `ACTIVE` unconditionally; resurrection is exempt from rung 21 and preserves all period/audit fields — `routes/hospice.py:65-69,151-153`
- **3.11** — insert — ambiguity — `service_date` is a full instant, compared instant-to-instant; creation nulls — `routes/claims.py:28,49,71-73`
- **3.11** — insert — ambiguity — `PAID` leaves `acp_minutes_claimed` alone; a 0-net `PAID` writes nothing — `cascades.py:65-74`
- **4** — insert (new paragraph) — ambiguity — every response is the whole row (nulls rendered, no internal keys), plus the exhaustive **15-field list of validated-but-never-persisted** request fields — `routes/*.py`, `envelope.py:34`
- **4 (table)** — revise — **mismatch** — symptom-assessment row said "against an ACTIVE care plan"; impl imposes no plan state — `routes/careplans.py:113`

### Heading-structure check
`diff` of all 32 `^#` lines between `PRD.md` and `PRD_COMPLETED.md`: **identical** — same headings, same order, none added or removed. Table row count identical (65 endpoint rows + error catalogue), code-fence count identical (4), ladder still 31 rungs.

### Areas that came back genuinely clean (already uniquely pinned by PRD.md) — useful doc-generator feedback
1. **Action-endpoint response entity** — §4's "returns the resource named by the identifier in its path" matches all 24 action endpoints and the clock exception exactly; zero drift.
2. **RBAC role lists** — all 65 endpoints' authorised-role lists match `config.py`/`auth()` exactly, including `ProgramAdmin` appearing everywhere and `Caregiver` being absent from `GET /patients/{id}`.
3. **Boundary inclusivity** — every `<`/`<=`/`>`/`>=` site in the implementation (triage floor 60, re-referral cap 2, witness/notary/POLST counts, ladder step 1, attestation window, early-refill, promotion SLA, conference 15-min gap, half-open DME windows, inventory availability, IDT 15 days, face-to-face 30-day window, 16 billable minutes, concurrent-care half-open period, MME threshold 90, distress tiers 70/40/15, coinsurance 10 000, unit cap 4) is already pinned on the correct side by PRD prose.
4. **The 16 calculations' rounding and evaluation order** — all five dual-variant calcs (triage, distress, MME, allowed-amount, benefit-period length) and the pinned-order breakthrough and money chains match `calc.py` step for step, including which discriminator selects which formula and whether the cap precedes or follows the tier lookup.
5. **Rung 5's applies-to list** — the 13 named creation endpoints match the implementation's `fk()` call sites exactly, with none missing and none extra.
6. **Rung 7's four deliberate widenings** — refill, DME `SCHEDULED`, conference attestation, document execution — match the implementation precisely, and each does unmask the rung the PRD says it unmasks.
7. **Rung 11's witness predicate** — including the "`is_beneficiary` disqualifies regardless of status, `REVOKED` included" clause, which the implementation honours exactly.
8. **404-vs-403-vs-409 routing on nested paths** — rungs 1→2→3 already fix that a bad role against a non-existent row is a 403, and rung 4-above-5 that a wrong-typed FK is a 400.
9. **The five records-freeze exemptions** — exactly the five endpoints the PRD names carry no freeze gate; no sixth, no missing one.
10. **Optional-field defaults** — every declared default (`opioid_status`, `is_beneficiary`, `surrogate_stated`, `prior_auth_required`, `concurrent_care_carve_out`) matches; the only default-adjacent silence was the *null-vs-omitted* equivalence, now pinned.

**Orchestrator independent verification:** `PRD.md` 466 lines / 118,507 chars → `PRD_COMPLETED.md` 470 lines / 142,103 chars. `diff` of the 32 `^#` heading lines is empty — headings identical, same order. Endpoint table row count 65 in both files. `SWEEP_DONE` marker removed from `implementation/`.

## Pipeline complete — 2026-08-03T19:46:41.394Z

Final state: 86/86 tests passing on all 8 sweep rounds, 0 deletions, 0 fixes of any kind. Step 8 skipped; Step 9 supplied all 50 completeness edits.
