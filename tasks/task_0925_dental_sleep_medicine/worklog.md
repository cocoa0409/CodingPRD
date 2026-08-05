# Worklog — task_0925_dental_sleep_medicine

Scenario (verbatim from user):
```
925. Dental Sleep Medicine (oral appliance): physician referral & diagnosis (HSAT/PSG), oral-appliance impression & fabrication, titration & efficacy re-test, medical (not dental) billing & DME, adherence & follow-up, warranty/repair, cross-provider coordination, recall
```
Difficulty: **beyond-Expert** (user asked for "hard than expert level").

## Step 1: Create task directory — 2026-08-04T04:00:00.000Z

Created `tasks/task_0925_dental_sleep_medicine/` and `tasks/task_0925_dental_sleep_medicine/workspace/`. Index 0925 (highest existing was 0924).

## Step 2: Generate scaffold — 2026-08-04T05:06:00.000Z

All three artifacts are written, parse clean, and pass `scaffold_lint.py`.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    70
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1799

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` (3715 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2449 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (7140 lines)

## Density delivered

| Dimension | Target | Delivered |
|---|---|---|
| Entities | 14–16 | **16** |
| Endpoints | 60–70 | **70** |
| Error codes | 30–36 | **37** |
| State machines | 10–13 (≥8 non-linear) | **13, of which 12 non-linear** (Appliance carries 3 parallel axes: lifecycle × device-hold × patient-recall; TitrationVisit HELD self-loop; PriorAuth/Claim capped denial-appeal cycles; SleepStudy repeat loop; LabOrder remake loop; EfficacyReport revision loop) |
| Calculations | 14–18 (5+ dual-variant) | **20, of which 9 dual-variant** |
| Ladder rungs | 20+ | **35** |
| OCC rules | 2–3 | **3** (Appliance / Patient / Referral parents) |
| Conservation invariants | 2–3 | **3** (protrusion mm, claim money, lot device population) |
| Cascade depth | ≥4 | **5** (lot recall → device hold → visit void → titration suspend → report withdraw → claim void), plus a depth-4 from sign-off and a depth-3 from LOSS repair |
| Declared constants | all valued | **34, every one carries an explicit numeric value** |

Design instances: 18 (§1.8, 2 per rule × 9 rules) and 69 (§1.9, across all nine claim-extraction-guide sections; 63 with full recipes, 6 `excluded_because` stubs). Every one of the 37 error codes is triggerable somewhere in the two design files; zero unbound `${var}`, zero duplicate captures, zero duplicate names across the union, zero unresolvable `grounds`, zero forbidden concurrency vocabulary.

Difficulty devices used: a **global write gate** (rung 5, payer audit hold, pre-empts rungs 6–35), a second narrower **device gate** (rung 13, lot recall hold), two **mutate-then-reject** rungs (diagnosis expiry on the path resource; prior-auth expiry on a non-path resource), **segregation of duties** (physician ≠ dentist; dentist may not sign his own efficacy report), and a **self-referential** Appliance replacement chain.

## Reachability / boundary defects found and repaired

1. **`ERR_STUDY_NON_DIAGNOSTIC` was unreachable** — a NON_DIAGNOSTIC study also has a null `severity_band`, so the band check fired first. Swapped rungs 16/17 so the status check precedes it.
2. **`ERR_SELF_REFERRAL` was unreachable on `POST /referrals`** — no Provider can be both SLEEP_PHYSICIAN and DENTIST, so the provider-suitability rung always pre-empted it. Swapped rungs 14/15; both codes now reachable.
3. **`ERR_EFFICACY_LOOP_OPEN` on `recall-check` was permanently masked** by that endpoint's own ACTIVE_THERAPY precondition (only reachable through loop closure). Clause deleted; the claim clause kept.
4. **`ERR_DEVICE_RECALL_HOLD` unreachable via `apply`** — the recall cascade voids every open visit first, so rung 12 wins. Documented as a designed pre-emption and named the four endpoints that do reach rung 13.
5. **Dead side effect**: "decline cancels RECORDS_CAPTURED lab orders" — a lab order cannot exist on a non-ACCEPTED referral. Removed; the EXPIRED-cascade leg retained.
6. **Care-team scope made first contact impossible** — twice: a dentist could never accept the referral that admits him (scope required ACCEPTED), and a physician could never order the first study. Added "any referral status" plus an explicit scope-bootstrapping clause.
7. **`RETIRED` (hence the whole replacement path) was reachable only through the full efficacy loop**. Added an `IN_TITRATION → RETIRED` edge for LOSS and widened rung 20's exemption to a RETIRED predecessor.
8. **Already-EXPIRED pre-emption had no gate** — rung 12 did not gate prior-auth creation on referral state, so the mutate-then-reject rung would have re-fired and double-bumped `version`. Added.
9. **Two live appliances were possible** — rung 20 covered create but not deliver. Extended to both.
10. **Rung 21 contradicted the state machine** — it was worded to gate every apply, but the SM's HELD and REDUCED edges carry no interval precondition. Restricted to the APPLIED outcome.
11. **Enum closure**: `WrittenOrder.VOIDED`, `TitrationVisit.RESCHEDULED`, `ApplianceLot.RECALL_RESCINDED` had no producing transition (removed); `Provider.SUSPENDED` had no producer (made settable at creation and wired into rung 15).
12. **Two test chains declared plateau before creating a further titration visit**, which rung 12 would have rejected — corrected in `titration_interval_beats_protrusion_ceiling` and the protrusion-ceiling corner instance.
13. **Duplicate capture name** `app_v1` in 8 generated instances — delivery-time capture renamed.

Boundary hittability was checked for every threshold and each has an exact-hit plus one unit either side, in units the endpoints actually accept: AHI 30.0 vs 29.9 (240 vs 239 events over 8 h), HSAT 240 vs 239 recorded minutes, adherence 21/30 = 0.7000 exactly vs 20/30 = 0.6667, pct-reduction exactly 0.5000 (18.0 → 9.0), protrusion 7.75 + 0.25 == 8.00 vs + 0.50, titration interval exactly 14 days vs 13, f2f 180 vs 181 days, PA validity 2026-08-03 vs 2026-08-04, repair cap 555 min = 37 units = 92500 vs 556 min = 38 units capped back to 92500, CPAP nights 30 vs 29, Epworth 10 vs 9, and the strictly-after useful-lifetime edge. Every formula-derived assertion in both design files was computed in Python against the §1.3 formulas before being written as a literal.

**Orchestrator independent verification:** all three files `yaml.safe_load` clean; `endpoints[]` = 70, `entities[]` = 16; ALL_CAPS sweep of SCAFFOLD.yaml → 110 tokens = 34 valued constants + 37 error ids + 39 enum members (+2 meta tokens), **0 undeclared**.

## Step 3: Copy INSTRUCTION.md — 2026-08-04T05:07:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0925_dental_sleep_medicine/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-04T05:27:00.000Z

PRD complete and verified. Final report:

## Output
`workspace/PRD.md` — **490 lines**, 116 KB, built through 9 bounded Write/Edit calls (no single large write).

**Sections:** 5 top-level (`## 1`–`## 5`) plus **20 `###` subsections** — 11 in §2 (RBAC · response envelope · pagination/filtering · identity+clock · serialized shape/versioning · the 35-rung ladder · OCC · enum routing · uniqueness · precision+conservation · cascades) and 9 in §3 (cast/audit · diagnosis · referral · payer paperwork · lab→device · titration · adherence+efficacy+recall · billing · repairs/recalls).

## Verification (all mechanical, scripted against SCAFFOLD.yaml)
- **34/34 constants** carry their value verbatim in prose. Zero-Silence holds. (`PREFAB_START_PCT` initially read only as "half of"; patched to `0.50 of max_protrusive_mm`.)
- **37/37 error ids** appear in §2/§3 narrative *and* in the §5 table.
- **70/70 endpoints** present in the §4 table (4 columns; §5 has 2 columns).
- **Contract 1 — Field coverage: PASS.** entities[].fields 153/153, request_body 101/101, query_params 26/26, path_params 16/16, non-entity output keys 9/9 → 0 missing. All state values and all enum members also present verbatim.
- **Contract 2 — Rule coverage: PASS.** 13 state machines / every transition (both branches rendered at equal density), 20 calculations (9 dual-variant, each with both formulas, the fork condition, worked numbers per branch, and rounding order), 35 validations with priority + applies_to, 3 OCC rules, 3 conservation invariants, depth-5 cascade.
- **Contract 3 — §3 path purity: PASS.** 908 backticked tokens scanned in §3; 0 leading-`/`, 0 bare-method, 0 method+path.
- §2.2 emitted byte-identical to `section-2.2-response-structure.md`. No fuzzy/approximating words.

## Run-specific requirements
- **Ladder:** all 35 rungs in strict order with exact error ids, plus an explicit "evaluated in ascending order, stops at first failure" statement. Rung 5 (payer-audit) stated as pre-empting **rungs 6–35** with its 7 exemptions; rung 13 (lot-recall device gate) as pre-empting **rungs 14–35**, including the designed unreachability on titration-apply (rung 12 wins with `ERR_INVALID_STATE`).
- **Mutate-then-reject:** both rungs rendered with all three clauses. Rung 18 → write (`EXPIRED` + version bump + LabOrder cancel), raise `ERR_DIAGNOSIS_EXPIRED`, and on a later call rung 12 pre-empts with `ERR_INVALID_STATE` and no second bump. Rung 29 → write (`PriorAuth` `EXPIRED` + bump), raise `ERR_PRIOR_AUTH_REQUIRED`, and on a later call **nothing pre-empts** (the auth is not the path resource) so the same error re-raises with **no** write and **no** bump.
- **Enum routing exhaustive:** all 18 entity fields + 6 action-verb body enums listed with member sets, plus explicit "no other field routes to `ERR_INVALID_ENUM`" and the free-text/type/domain fields that route to `ERR_VALIDATION` instead.
- **Timestamps:** one uniform rule — instants as `…T…:…:….sssZ` (3 digits), caller-supplied instants **re-rendered canonically, never echoed**; the 30 date-valued fields enumerated and rendered as bare `YYYY-MM-DD`; `created_at`/`updated_at` are real server instants, distinct from the logical clock (default `2026-05-01T00:00:00Z`).
- **Response shape:** per-entity field lists for all 16 entities, `AdherenceDownload` explicitly without `updated_at`/`version`; **one version bump per row per request** (never per field or per cascade level), with the response projected **after** commit.
- **Lists:** `created_at` ascending, insertion-order tie-break (also governing the "newest row" selections); off-enum filter → **empty page**, not an error; bad `limit`/`offset` → `ERR_VALIDATION`.

## Scaffold contradictions carried forward as explicit, neutral friction points
1. **Titration interval on a reduction** (§3.6) — rung 21 says the 14-day gate applies *only* to `NONE`/`MILD`; the `SCHEDULED → REDUCED` edge lists it as a precondition. Divergence: a `SEVERE` reduction inside 14 days.
2. **Repair-order parent state** (§3.9) — rung 12 ("past `DELIVERED`, not `RETIRED`/`REPLACED`") vs the enumerated set; they differ on `TITRATION_SUSPENDED` → `ERR_INVALID_STATE` vs `ERR_DEVICE_RECALL_HOLD`.
3. **LOSS retirement cascade** (§3.9) — repair creation admitted from `TITRATION_PLATEAU`/`EFFICACY_PENDING`, but no `RETIRED` edge is declared out of either.
4. **Efficacy re-submission** (§3.7) — rung 12 demands `TITRATION_PLATEAU`, which a `DISPUTED → SUBMITTED` re-submit can never satisfy; strict reading makes the revision cycle unreachable.
5. **Recall cadence basis** (§3.7) — calculation and variant measure the next due date from the *check* date; the `DUE → NOT_DUE` edge says the *due* date.
6. **`retired_count` timing** (§3.9) — computed at issuance per the calculation and Conservation 3; the field description says "at remediation time".
7. **Appeal from `DENIED_FINAL`** (§3.4) — the nominated `ERR_APPEAL_LIMIT_REACHED` requires the state gate to admit `DENIED_FINAL`; a strict rung-12 reading yields `ERR_INVALID_STATE` and makes the nominated id unreachable.
8. **Suspended-provider slots** (§3.1) — the field description names 4 slots, rung 15 names 5 (adds `ordering_physician_id`).
9. **`medical_payer_id` must be `MEDICAL`** (§3.1) — no rung enforces it at patient registration; surfaces later as `ERR_DENTAL_PAYER_ROUTING`.
10. **Superseding a referenced `SIGNED` order** (§3.4) — precondition exists, no error id declared; rendered as "older order stays `SIGNED`, new order still created".
11–12. Two preconditions with **no declared error id**, routed to `ERR_VALIDATION` and flagged as such: `signed_on >= order_date` (§3.4) and `date_of_service == delivered_on` for `INITIAL_DEVICE`/`REPLACEMENT` (§3.8).

Two benign header slips were *not* rendered in the PRD (comment-level, no rule conflict): the §1.3 banner says "18 calculations" for a 20-entry block, and rung 10 says "EXACTLY these three identifiers" then lists four and self-corrects in the same sentence ("Four fields across four entities") — the PRD states four.

## Step 5: Generate unit tests — 2026-08-04T05:59:00.000Z

Test infrastructure and suite generated. Final report:

## Output

- `test_helpers/` — 9 modules (~2,000 lines): `types.py` (32 enums + 16 entity TypedDicts, `AdherenceDownload` correctly omits `updated_at`/`version`), `api_client.py` (all 70 endpoints), `api_errors.py` (37 ids + status map registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py`.
- `test_suite/` — `conftest.py` + 10 test files, **103 tests**.

## Coverage

- **Queue A (difficulty): 18/18 instances translated**, ≥2 tests each — 41 tests total.
- **Queue B (corner): 62/63 non-stub instances translated** — 62 tests. 6 `excluded_because` stubs not translated; all 6 `difficulty_instance` cross-references resolve.
- `def test_` = 103, `Design:` tag count = 103, every docstring ends with exactly one tag, all tags resolve to a real instance in the right rule_id/section.
- **0** `@pytest.mark.skip` / `xfail` / `skipif`.

## SKIPPED instance (1)

- `Corner/state_machines/efficacy_report_dispute_then_resubmit_revision_cycle` — **not uniquely derivable**. PRD §3.7 renders friction point 4 neutrally: the state gate requires the appliance to be `TITRATION_PLATEAU` for an efficacy-report submission, but a post-dispute re-submission finds it in `EFFICACY_PENDING` or `IN_TITRATION`, and the PRD states outright that "Read strictly against the appliance state, the revision cycle would be unreachable." A test asserting `st_resub == SUBMITTED` bets on one reading.

## Friction points landed on and how they were handled

- **SEVERE reduction vs. the 14-day interval** — `advancement_conservation_across_held_and_reduced` reaches `REDUCED` via the **`HELD → REDUCED`** edge, which PRD §3.6 explicitly says "lists no interval precondition at all". Both readings agree, so the instance is derivable and was kept.
- **Appeal from `DENIED_FINAL`** — `test_appeal_beyond_the_cap_is_refused` uses `validate_error_is_one_of([ERR_APPEAL_LIMIT_REACHED, ERR_INVALID_STATE])` (the skill's sanctioned `error-precedence` pattern) rather than betting on the nominated id.
- **Recall cadence basis** — the corner instance's check is performed from `LAPSED`, where PRD §3.7 is explicit ("recomputed from the date the check was actually performed"). Derivable; kept.
- **`retired_count` timing** — the conservation instance has zero retired devices at issuance, so both readings give 0. Kept.
- **Superseding a referenced `SIGNED` order** — the corner setup has no appliance referencing it, so the qualification does not bite. Kept.
- Repair-order state on `TITRATION_SUSPENDED`, LOSS out of `TITRATION_PLATEAU`/`EFFICACY_PENDING`, suspended-provider slot count, `medical_payer_id` enforcement point, and the two `ERR_VALIDATION`-routed preconditions were not reached by any design instance's asserted outcome.

## Run-specific requirements

- **Instant comparison**: `parse_instant()` / `assert_same_instant()` in `assertions.py`; `assert_calendar_date()` parses both sides for every date-valued field. **Raw `== "20…` timestamp equality count in `test_suite/`: 0.** `set_clock()` verifies `current_utc` semantically on every clock move.
- **Segregation of duties**: per-role, per-identity builders (`make_sleep_physician_headers`, `make_dentist_headers`, `make_lab_technician_headers`, `make_patient_headers`). Fixtures mint physician ≠ dentist ≠ lab as distinct `Provider` rows; `extra_dentist` / `second_patient` / `suspended_dentist` knobs mint additional distinct identities. The self-referral tests deliberately construct `make_sleep_physician_headers(dent_id)` to exercise rung 14.
- **API-only state**: every precondition is built by a chain of declared endpoints (`build_scenario` walks a 15-stage timeline, re-reading OCC parent versions before each guarded create).
- Written incrementally; `pyflakes` clean; 103 tests collect cleanly under pytest.

One correction worth flagging: the corner instance `lab_order_remake_cycle_increments_remake_count` is internally inconsistent — its `setup_api_calls` set the clock to 2026-05-01 while its `setup:` prose and its pre-computed `promised_ship_date == 2026-05-11` require a 2026-05-04 submission. The test follows the prose and the pre-computed literal by setting the clock to 2026-05-04 before the first submit.

## Step 6: Generate implementation — 2026-08-04T05:54:00.000Z

Implementation complete and verified.

## What was built

`workspace/implementation/` — **20 files (18 Python modules + `start.sh` + `requirements.txt`), 3,350 lines**, written incrementally in bounded Writes. Layout: `errors.py`, `store.py` (in-memory dicts + logical clock + round-half-up/add-months), `envelope.py`, `validation.py` (rungs 7/8/9), `access.py` (rungs 1–6, 13, version-bump tracking), `serializers.py`, `calc.py` (all declared constants), `domain.py` (cascades, mutate-then-reject, SWO selection), and 8 route blueprints.

## Required reports

**url_map diff: 70/70 matched, MISSING 0, EXTRA 0.** Booted in-process, dumped `app.url_map`, normalized `{param}`/`<param>` on both sides, diffed against the 70 `endpoints[]` entries programmatically.

**Timestamp rule.** One uniform rule, single code path (`store.render_instant`): `created_at`, `updated_at`, `api_request_timestamp` and the clock's `current_utc` render as ISO 8601 UTC with exactly 3 fractional digits and trailing `Z` (`2026-05-01T00:00:00.000Z`). `created_at`/`updated_at` are **real server wall-clock** instants (§2.4 makes them independent of the business clock); all business dates come from the logical clock. Caller-supplied instants are re-rendered canonically, never echoed — verified over HTTP that `to_iso8601: "...09:30:00.123456Z"` returns `...09:30:00.123Z`, and a plain `Z` returns `.000Z`. All 30 date-valued fields are stored as `date` objects and render bare `YYYY-MM-DD`. Audited: the only `isoformat()` calls in the tree are on date objects; the only wall-clock read is `now_instant()`.

**Enum routing.** Implemented as the closed iff-rule with **24 entries** (18 request-body fields + 6 action-verb body enums), declared as `Field(enum=...)`. Only a listed field can reach `ERR_INVALID_ENUM`; every other failure — wrong JSON type (including a non-string on an enum field), out-of-domain number, malformed date, unknown field, free text — is `ERR_VALIDATION`.

**Persistence grep** for `sqlite|json.dump|open(|pickle|/tmp` over the implementation: **empty** (exit 1). Storage is Python dicts; nothing is seeded at startup.

## Friction points and readings chosen (14)

1. Suspended-provider slots (4 vs 5) → **all five slots**, ladder is the enforcement path. 2. PA/claim appeal from `DENIED_FINAL` → **state gate admits DENIED + DENIED_FINAL, rung 35 decides**, keeping `ERR_APPEAL_LIMIT_REACHED` reachable. 3. 14-day interval on a SEVERE reduction → **ladder: NONE/MILD only**. 4. Efficacy re-submission appliance state → **plateau gate applies only to the first submission**, so the revision cycle is reachable. 5. Recall-check next due date → **from the check date + 365** (the calculation, which §3.7 says governs both arms). 6. Repair creation from `TITRATION_SUSPENDED` → **looser ladder phrasing**, so it falls through to rung 13 `ERR_DEVICE_RECALL_HOLD`. 7. LOSS repair from `TITRATION_PLATEAU`/`EFFICACY_PENDING` → **retire from every admitted state**, same cascade. 8. Lot `retired_count` → **frozen at issuance** (Conservation 3). 9. Rung 18 on the DECLINED arm → **ladder: whole endpoint**. 10. Client-supplied `id` (§2.4 "ignored" vs §2.8 "unknown field") → **`id` ignored, all other undeclared fields 400**. 11. "Three vs four" unique identifiers → **four**. 12. Rung 6 on physician-response → **scope admits referring physician + treating dentist**, so rung 14 returns `ERR_SELF_REFERRAL` as declared while unrelated providers still fail rung 6. 13. Care-team scope on list endpoints → **filter out-of-scope rows** (matching "restricted to his own rows"); single-row reads still 403. 14. Rung 13 over "claim writes" → **all four claim writes plus repair complete**.

## Verification

Three self-written suites (~180 assertions) all at 0 failures, plus a live `bash start.sh` HTTP boot on `$PORT`/`0.0.0.0`: full clinical→billing path; both dual-variant severity denominators (HSAT 11.3 vs PSG 15.0); custom 4.75 mm vs prefab 4.00 mm starting advancement; both adherence denominators (0.6667/0.8333); money waterfall (50000/27000/77000/108000) and the rejected 87000 alternative; 5-level recall cascade with counters; both mutate-then-reject rungs **including the third clause** (already-EXPIRED referral → `ERR_INVALID_STATE`, no second bump; already-EXPIRED PA → same error, no second bump); LAPSED-skips-DUE clock sweep; LOSS cascade; loaner half-open intervals; appeal cap; and version granularity (one bump per row per request, projected post-commit).

**Orchestrator note on isolation:** Steps 5 and 6 were launched concurrently in one message. Step 6 finished ~5 min before Step 5, so `implementation/` existed on disk for the tail of test-gen's run (the reverse of the intended one-way isolation). Containment checks: `grep -rn "implementation/\|from app\|import app" test_suite/ test_helpers/` → 0 hits; all 103 tests carry a `Design:` tag resolving to a §1.8/§1.9 instance, so every assertion traces to the design index rather than to impl behavior.

## Step 7: Run tests and iterate — 2026-08-04T06:20:00.000Z

Done — all 8 rounds green at 102/102.

## Summary

**Iterations run:** 2 sweeps (8 rounds each, 4 waves of 2).

- **Sweep 1:** 102/103 in all 8 rounds. Exactly one failure, deterministic (all 8 rounds, not flaky): `test_titration_visit_cannot_be_scheduled_on_a_fabricated_device` — `AssertionError: Expected response_type 'error', got 'object'`.
- **Sweep 2:** 102/102 in all 8 rounds, union of failures empty.

**Tests deleted (1)**

`test_05_titration.py::test_titration_visit_cannot_be_scheduled_on_a_fabricated_device` — **PRD silence (STEP 1a)**, compounded by articulable divergence (STEP 1b).

The test asserted that creating a titration visit against a `FABRICATED` appliance returns `ERR_INVALID_STATE`. The PRD never states that. Evidence:

1. Its own docstring quotes the sentence that sinks it. PRD §2.6 rung 12 reads *"A titration **apply** requires the appliance's `lifecycle_status` to be `DELIVERED` or `IN_TITRATION`"* — the test exercises a *create*.
2. The scoping is deliberate and contrastive: the same sentence says "creation" for five other operations (lab-order creation, prior-authorisation creation, appliance creation, repair-order creation, claim submission). It demonstrably knows how to say "creation" when it means it.
3. PRD §3.6 line 303 is the complete titration-visit creation paragraph and enumerates creation's requirements exhaustively — the four body fields, the `ACTIVE`/`DENTIST` provider check, the increment domain, `expected_appliance_version` — with no lifecycle precondition.
4. Rungs 11 (OCC) and 15 (provider suitability) each explicitly name "titration-visit creation" in their applicability lists. Rung 12 does not.
5. PRD line 171 confirms the two are distinct operations: *"on a titration apply, rung 13 is unreachable... The rung is reached instead through titration-visit creation."*
6. The endpoint table (line 423) describes `POST /titration-visits` with no state guard.

Root cause: the scaffold design instance `Difficulty/cross_entity_state_dependency/titration_visit_create_requires_delivered_appliance` extrapolated a create-side gate from its cited grounds `validations[priority=12]` — but that scaffold rung itself reads *"a TitrationVisit **apply** requires Appliance.lifecycle_status in {DELIVERED, IN_TITRATION}"*, and the PRD rendered it faithfully. A scaffold-only rule with no PRD prose behind it, so unfair per the read-PRD-only contract.

Coverage was not orphaned: `test_applied_visit_is_terminal_and_cannot_be_reapplied` still exercises rung 12's `ERR_INVALID_STATE` on the apply path.

**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `test_suite/`:** none beyond the deletion above.
**Fixes applied to `implementation/`:** none — the implementation was already correct under the PRD's literal reading. Verified untouched; the only file modified across the whole session is `test_suite/test_05_titration.py`.

**Final counts:** 102/102 passing, all 8 rounds in agreement, zero flakiness. Storage confirmed in-memory dicts only (no sqlite/pickle/file/tmp writes), so `start.sh` re-invocation wipes all state as required.

**Orchestrator independent verification:** all 8 `results.N.json` re-parsed → 102 individual rows each, `{'passed': 102}`, name-sets byte-identical across all 8; `def test_` count == `Design:` tag count == 102; `@pytest.mark.skip|xfail|skipif` = 0; `find implementation/ -name '*.py' -newer results.1.json` → empty.

## Step 8: Finalize PRD — 2026-08-04T06:24:00.000Z

`PRD_FINALIZED.md` written with exactly one edit, matching the thin diff.

## Line counts
- `PRD.md`: 490 lines / 116,386 bytes
- `PRD_FINALIZED.md`: 490 lines / 116,750 bytes
- Delta: 0 lines (+0.00%), +364 bytes (+0.31%) — one sentence inserted mid-paragraph on line 303.

## Changes
- **§3.6 Titration at the Chair (line 303)** — insert — pins that titration-visit *creation* has no `lifecycle_status` precondition on the appliance (rung 12 governs the apply only), so a visit may be scheduled against a `FABRICATED` appliance — `implementation/routes/titration.py:20-66` (create, no gate) vs `implementation/routes/titration.py:110` (apply, the only gate).

## Pre-edit search log

**Edit 1 — §3.6 line 303**

(a) **Subject identified:** the relationship between `Appliance.lifecycle_status` and the two titration-visit operations (create vs. apply); secondarily, what *else* creation is gated on, so the new sentence does not accidentally claim creation is unconditional.

(b) **Impl paths enumerated, read/grepped:**
- `grep -rn "titration_visits"` across `implementation/` — only four sites: the single write site `routes/titration.py:53` (`new_row`), the read helper `domain.py:34` (`visits_of`), the list projection `routes/titration.py:93`, and the path-resolution map `access.py:35`. Confirms `POST /titration-visits` is the *only* creation path; no cascade, no other endpoint, no factory creates a visit.
- `routes/titration.py:20-66` `create_visit()` read in full — full precondition set is: rung 1/2 `actor(["Dentist"])`, rung 4 `body_refs`, rung 5 `gate_frozen`, rung 6 `require_scope`, rungs 7/8 field presence/type, increment domain (0.25–2.00, quarter-multiple), rung 11 `expected_appliance_version` → `ERR_STALE_VERSION`, rung 13 `gate_device` → `ERR_DEVICE_RECALL_HOLD`, rung 15 dentist `DENTIST`/`ACTIVE`. **No `lifecycle_status` read anywhere in the function.** Supersede loop and `visit_seq` also run unconditionally on lifecycle.
- `routes/titration.py:96-151` `apply_visit()` — line 110 is the sole `lifecycle_status not in ("DELIVERED","IN_TITRATION")` → `ERR_INVALID_STATE`, i.e. exactly the PRD rung-12 sentence, unchanged.
- `grep -n "lifecycle_status" implementation/*.py implementation/routes/*.py` — all 32 hits reviewed to confirm no indirect create-side gate: `appliances.py` 123/159/176/206/227 (deliver/POD/plateau/remediate/recall-check), `efficacy.py` 46/127/140/181/191, `billing.py:259`, `domain.py` 147/161/178/201/231/237 (retire, recall cascade, recall posture, replacement). None of these run on visit creation; none of them read a visit's creation path.
- `access.py` read in full for `gate_frozen` (rung 5) and `gate_device` (rung 13) semantics, to be sure the new sentence's "provided the ladder's other rungs … are satisfied" is accurate rather than a blanket permission.
- PRD cross-references checked for consistency with the new wording: line 144 (rung 12, says "apply", untouched), line 143 (rung 11 names "creation of titration visits"), line 147 (rung 15 names "titration-visit creation"), line 171 (states rung 13 "is reached instead through titration-visit creation"), line 116 (TitrationVisit fields), line 423 (endpoint table, no state guard). All remain true.

(c) **Wording adjustment made:** the first draft opened with "Those are the whole of creation's preconditions" — rejected as a false universal, since creation still enforces the rung-5 write gate and the rung-13 recall gate, neither of which that paragraph lists. Rewrote as a claim scoped strictly to `lifecycle_status`, and appended the explicit carve-out "provided the ladder's other rungs, the recall gate of rung 13 among them, are satisfied" so the sentence cannot be read as making creation unconditional. Also kept the italic *apply* to mirror line 171's existing "on a titration *apply*" phrasing, so the two passages reinforce rather than compete.

No other edits: the diff contains zero implementation fixes, zero test_helpers fixes, and one deletion whose only PRD-visible consequence is the create/apply scoping pinned above.

## Step 9: Complete PRD — 2026-08-04T06:44:00.000Z

`workspace/PRD_COMPLETED.md` is written. Structure is byte-for-byte identical in shape (28 headings, 111 table rows, 4 code fences, same 490 lines) — every change is an in-paragraph insert or revision.

## Stats

- **PRD_FINALIZED.md**: 490 lines, 116,750 chars → **PRD_COMPLETED.md**: 490 lines, 135,367 chars (**+18,617 chars**)
- **53 lines changed**; **41 ambiguity-pins**, **12 mismatch-revisions**
- All 70 endpoints, 37 error codes and the §4 role table were diffed against the code; role lists and error statuses already matched exactly (no change).

## Mismatches (PRD actively misdescribing correct code) — 12

- **§2.6 rung 12** — revise — repair-order state gate said "past `DELIVERED`", which excludes `DELIVERED`; impl refuses only `FABRICATED`/`RETIRED`/`REPLACED` — `routes/billing.py:259`
- **§2.6 rung 12** — revise — efficacy submission "requires `TITRATION_PLATEAU`" unconditionally; impl gates it only on the `DRAFT` arm — `routes/efficacy.py:127`
- **§2.6 rung 14** — revise — "Any *other* provider id fails rung 6 first"; impl lets an in-scope non-referring physician through rung 6 to `ERR_SELF_REFERRAL` — `routes/efficacy.py:156,170`
- **§2.6 rung-13 gate ¶** — revise — "every … claim write"; impl exempts claim **appeal** (14 gated endpoints enumerated) — `routes/billing.py:216`
- **§3.3** — revise — referral response ran currency "on the accepting arm"; impl runs rung 18 before the `decision` is read, so `DECLINED` expires too — `routes/clinical.py:281-284`
- **§3.4** — revise — appeal friction left `DENIED_FINAL` unadjudicated; impl admits both denial postures — `routes/paperwork.py:223`
- **§3.6** — revise — 14-day interval friction; impl evaluates it only on `NONE`/`MILD` — `routes/titration.py:118-121`
- **§3.7** — revise — efficacy re-submission friction; impl scopes the plateau gate to `DRAFT` — `routes/efficacy.py:127`
- **§3.7** — revise — recall next-due friction; impl always uses check date + 365 — `routes/appliances.py:234`
- **§3.9** — revise — repair from `TITRATION_SUSPENDED` friction; impl falls through to `ERR_DEVICE_RECALL_HOLD` — `routes/billing.py:259-261`
- **§3.9** — revise — "no repair claim may be created against" a `NOT_COVERED` order; impl has no such rung (`billable` stays true, basis becomes 0) — `routes/billing.py:341-343`, `calc.py:161-168`
- **§3.9** — revise — `retired_count` divergence "recorded rather than resolved"; impl freezes all four counters at issuance — `domain.py:164-167`

## Ambiguity pins (41) — grouped

- **§2.1** — care-team scope: list endpoints *filter* (403 only on single-row); full identity-vs-membership split across all endpoints; written-order create does not bootstrap (`access.py:136-155`, `paperwork.py:26-29`)
- **§2.2** — `api_request_id` shape; `api_request_timestamp` reads wall clock, not the logical clock (`store.py:58-84`)
- **§2.3** — `total_count` counted after the scope filter (`domain.py:213-223`)
- **§2.5** — six named non-bumping branches (HELD apply, zero-deductible payment, unchanged loop count, second audit hold, repair completion, non-`ACTIVE_THERAPY` predecessor); newly created rows never bump (`access.py:168-198`)
- **§2.6** — body parsed between rungs 3 and 4; rung-12 completion list for all remaining transitions; rungs 26–28 use the server-selected order, not the body's `written_order_id`; rung 27 skipped when `delivered_on` is null; rung 35 reachable from `DENIED_FINAL` (`domain.py:112-131`, `validation.py:70-76`)
- **§2.8/§2.10/§2.11** — `id` is the sole unknown-field exemption; `mean_hours_per_worn_night` unrounded; recall cascade writes through the rung-5 freeze
- **§3.1–3.5** — loop-count recompute triggers + write-on-change; second audit hold; hold's `payer_id` unconstrained; PSG with no `sleep_minutes`; reorder identity; rung-15 slot precedence; patient version bumps on every order issue; approval keeps `denial_reason`; lab-order create/submit identity + submit skips rung 18; receive preserves `submitted_on`/`promised_ship_date`; predecessor untouched unless `ACTIVE_THERAPY`; fabrication into a recalled lot is not held; the `RETIRED` half of the live-device exception is vacuous; delivered `written_order_id` persisted verbatim
- **§3.6–3.9** — "most recent applied" ordering key; HELD writes no appliance row; `source`/role independence; `due_by` null; baseline 0.0; signing never clears `dispute_reason` and starts recall regardless of lifecycle; PARTIAL clears `plateau_declared_on` regardless; sweep scope + no backward moves; claim's appliance/patient untied; PA expiry boundary strict; `denial_error_id` survives a later payment; `K0739` basis 0 with no repair order; `labor_units` survives the charge zeroing; LOSS retires from every state (visits superseded only from `IN_TITRATION`); loaner unconstrained; recall level 3 always fires; level 4 leaves referral `status`; remediation check order + voided visits never restored

**Orchestrator final verification:** `find implementation/ test_suite/ test_helpers/ -newer results.1.json -type f` → empty (Steps 8 and 9 touched only PRD files), so the green 102/102 x8 result still describes the shipped tree. All 8 `results.N.json` present. PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md all 490 lines.

## PIPELINE COMPLETE — 2026-08-04T06:45:00.000Z
