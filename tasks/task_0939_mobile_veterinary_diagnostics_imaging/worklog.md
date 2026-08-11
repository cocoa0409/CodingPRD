# Worklog — task_0939_mobile_veterinary_diagnostics_imaging

Scenario (verbatim): `939. Mobile Veterinary Diagnostics & Imaging: referral & appointment, mobile-unit route & clinic scheduling, study acquisition & specialist read, report turnaround, equipment & tech, per-study billing to clinic, STAT/emergency, QC`

Difficulty target: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-09T04:35:38.815Z

Created `tasks/task_0939_mobile_veterinary_diagnostics_imaging/` and `workspace/`. Index 0939 chosen to match the idea-file index (`idea/0709.en.txt:39`), consistent with every prior run in this roster.

## Step 2: Generate scaffold — 2026-08-09T05:38:00.000Z

Scaffold generated and lint-clean. Files at `/home/ubuntu/github/CodingPRD/tasks/task_0939_mobile_veterinary_diagnostics_imaging/`.

### Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    87
  §1.1 entities declared:     19
  §1.8 instances scanned:     20
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1145

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Metrics

| Dimension | Value | Target |
|---|---|---|
| Entities | 19 | 17–19 ✓ |
| Endpoints | 87 | 72–84 (3 over) |
| Error codes | 74 | 44–58 (over; 15 are per-entity 404s) |
| Ladder rungs | 50, contiguous 1–50, single ladder | 40–50 ✓ |
| Calculations | 37, **10 dual-variant** | 24+/7+ ✓ |
| Status axes | 24 enum axes, 15 with full state machines, **15 non-linear** | 14+/≥12 ✓ |
| OCC rules | 4 (Route, Study, Invoice, ClinicContract) — all verified: `common_fields: true`, `expected_*_version` required in `input:`, version bump in `side_effects:`, 412 | 3+ ✓ |
| Conservation invariants | 6 (money, block count, route time partition, TAT partition, study disposition count, single live report) | 4–6 ✓ |
| Deepest cascade | **6 entity hops** — QcCheck→Equipment→Study→ChargeLine→BlockLedgerEntry→ClinicContract (plus a 5-hop STAT-bump cascade from a different trigger) | 5+ ✓ |
| Write-gate block | ordered G1..G5 at rungs 8–12, pre-empting rungs 13–50 | ✓ |
| Declared constants | **40 global + per-calculation repeats; zero undeclared** (constant-shaped-token scan returned only enum members, error ids and invariant ids) | ✓ |
| Design instances | 20 (§1.8, ≥2 per rule, 3 combinatorial modes a/b/c) + 64 (§1.9, 5 stubs) = 84, names unique, 0 unbound `${var}`, 0 unresolvable grounds, **all 74 errors named by ≥1 instance** | ✓ |
| Line counts | SCAFFOLD 4337 · DIFFICULTY 2114 · CORNER 4253 | |

### Domain seams realised
Two pipelines on one ladder (MOBILE vs TELERAD, with `ERR_NOT_APPLICABLE_TO_TELERAD` / `ERR_STUDY_KIND_MISMATCH`); STAT as a re-pricing + re-sequencing + **non-monotone re-clocking** axis (upgrade at 11:00 on a study acquired 09:30 → BREACHED with zero time passing: 160/240 accrued → 90/60); dual TAT accrual modes with `elapsed = accrued + paused`; route capacity in two independent units (`min(window, unit.max_shift_minutes)` with a buffer term, plus `max_stops`); retroactive QC quarantine with an inclusive `acquired_at >= last_passing_qc_at` cutoff; four parallel QC axes; specialist modality × species × STAT credentialing with a capped attempt counter; PRELIMINARY→FINAL→ADDENDUM with supersession and retraction; **dual-variant billing** (block draw 20000 vs list 26000 on byte-identical studies); **non-monotone trip fee** (12500 split 2 ways = 6250 each; one sibling leaves the billable set → survivor rises to 12500 and its invoice line is re-priced upward while the invoice total falls); floor-plus-remainder allocation pinned as [4167, 4167, 4166].

### Reachability self-repairs made (14)
1. Dropped the `shift_end − shift_start ≤ max_shift_minutes` route constraint — otherwise the minutes ceiling was unreachable without violating stop geometry; budget is now `min(window, unit cap)`, crossable at exactly 120 (passes) and 150 (fails).
2. Trip-share re-allocation cascade moved off `Study ORDERED→CANCELLED` (an ORDERED study was never in the billable set, so the cascade was a no-op) onto the reachable `qc PENDING_QC→REPEAT_REQUIRED` edge.
3. Deleted `ChargeLine.kind = TRIP_FEE_UNALLOCATED` — no reachable producer; `ChargeLine.study_id` became non-nullable.
4. Deleted `BlockLedgerEntry.reason = REFUND_CANCEL` — no producer (a cancelled study never draws a block unit).
5. Deleted `Route.status = CANCELLED` after dropping `POST /routes/{id}/cancel`.
6. Rewrote rung 3's FieldTech/acquire clause (actor must equal the **body's** `technician_id`) so rung 24 (that technician must staff the route) is not fully masked.
7. Split rung 23 into a STATUS limb (applies at `POST /routes`, dispatch, acquire, qc-checks) and a CERTIFICATION limb (acquire/qc-checks only) — otherwise `ERR_TECHNICIAN_NOT_CERTIFIED` was unreachable at acquire and `ERR_TECHNICIAN_INACTIVE` unreachable anywhere.
8. Widened rung 36 so a report author retains reporting rights after FINAL publication completes the assignment — otherwise the ADDENDUM path and `ERR_ADDENDUM_WINDOW_CLOSED` were unreachable.
9. Widened rung 48 so a study with `cancellation_fee_cents > 0` is postable — otherwise `CANCELLATION_FEE` lines had no producer.
10. Added `Study.escalated_at`; `tat_anchor_at` had referenced an undeclared instant.
11. Added CASCADE HOP 4c (surviving-sibling trip-share re-pricing) to the quarantine cascade so the money-conservation arithmetic closes.
12. Stated that a calibration window entirely in the past is accepted and computes EXPIRED — needed to reach `ERR_EQUIPMENT_CALIBRATION_LAPSED` without rewinding the clock.
13. Permitted `escalate-stat` from any non-terminal `workflow_status` — the mid-flight upgrade seam was otherwise blocked by the Study state rung.
14. Reworded two innocent uses of "simultaneously" (forbidden-vocabulary scan now returns zero hits across all three files).

Also pinned explicitly rather than left to guesswork: gate **G1 rejects a FAIL QcCheck outright** when its blast radius touches a FINALIZED invoice's ACTIVE lines (a billing freeze blocking a safety action, with no override path), and `POST /studies/{id}/qc` carries no ownership clause so any active FieldTech can QC a TELERAD study no technician ever touched.

### Orchestrator independent verification
- All three files `yaml.safe_load` cleanly; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (no test-answer leakage into the PRD input).
- Section counts re-derived from disk: 19 entities / 15 state_machines / 4 concurrency_rules / 37 calculations / 50 validations / 87 endpoints / 74 errors / 6 conservation_invariants / 6 roles / 40 global_constants.
- Independent ALL_CAPS constant sweep: 29 residual tokens, all accounted for as enum members (ChargeLine kinds, ledger reasons, notification kinds, pricing modes), `INV_*` invariant ids, or the `ERR_XXX` placeholder inside the `response_envelope` example at SCAFFOLD.yaml:44. **Zero undeclared constants confirmed.**

## Step 3: Copy shared files — 2026-08-09T05:40:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-09T05:56:00.000Z

PRD generated at `workspace/PRD.md`.

### Scale
**605 lines, 18,232 words.** Structure: §1 Introduction (3 paras) → §2 with 11 subsections (2.2 emitted verbatim) → §3 with 9 domain subsections → §4 endpoint table (4 columns) → §5 error table (2 columns). Written in 12 bounded appends; no single write exceeded ~120 lines.

### Coverage audit (machine-verified against SCAFFOLD.yaml)

| Inventory | Covered / Total |
| --- | --- |
| Endpoints (paths present in doc) | **87 / 87** |
| Error codes (present in §1–§3 *prose*, not merely §5) | **74 / 74** |
| Ladder rungs (numbered 1–50 in §2.8) | **50 / 50** |
| Calculations | **37 / 37** |
| State machines (all 55 distinct state values in backticks; all 15 state fields named) | **15 / 15** |
| Global constants (value recoverable) | **40 / 40** |
| Conservation invariants (§2.10) | 6 / 6 |
| Write gates G1–G5 (§2.9) | 5 / 5 |

Two constants are rendered semantically rather than literally, deliberately: `ROUNDING_MODE: round_half_up` → "rounded half up"; `TAT_BREACH_COMPARATOR: ">"` → "strictly greater than… 240 accrued is still `ACCRUING`, 241 is `BREACHED`".

### Hard contracts

```
Contract 1 — Field-Name Coverage
  entities[].fields:        139 required, 139 present, 0 missing
  endpoints[].input:         85 required,  85 present, 0 missing
  query_params:               2 required,   2 present, 0 missing
  path_params:               19 required,  19 present, 0 missing
  computed-output idents:     9 required,   9 present, 0 missing
                              (pricing view + current_utc)
Status: PASS

Contract 2 — Rule Coverage
  validations[] priority:    50 checked, 50 expressed as an ordered ladder (§2.8)
  concurrency_rules[]:        4 checked, 4 expressed (endpoint + expected_<parent>_version
                              + ERR_STALE_VERSION + 412) — §2.7
  state_machines[].transitions: 15 machines / 55 states, all from→to pairs,
                              preconditions and side-effects in prose
  calculations[]:            37 checked, 37 fully expressed, 0 pseudocode
  validations[] conditions:  74 error ids matchable to a condition in §2/§3
  side_effects / applies_to: all gate scopes enumerated exhaustively
  entities[].fields structured content: defaults, sources, enums, null-initial
                              values placed on owning entities
  sibling-branch symmetry:   G4 pair, rung-13 pair, rung-40 pair, rung-46 pair,
                              rung-47 pair, PIPELINE/COMMITTED, BLOCK_RATE/LIST_PRICE,
                              provider/clinician repeat, live/frozen invoice total
Status: PASS

Contract 3 — §3 Path Purity
  backtick tokens scanned in §3: 1092
  tokens starting with `/`: 0 · bare HTTP methods: 0 · method+path: 0
Status: PASS
```

### Friction points rendered un-adjudicated (both readings in prose)

1. **§3.9 — does cancelling an `ORDERED` study move sibling trip shares?** The endpoint's own summary says cancellation "RAISES the trip share of every surviving billable study at the same stop"; the `ORDERED → CANCELLED` transition note says an ordered study "was never a member of the stop's billable set… so cancelling one does NOT move any sibling's trip share." Both rendered; same tension extended to not-performed and clinic-side appointment cancel.
2. **§3.4 — no-show reachability.** No-show requires `Appointment.status == SCHEDULED` **and** the stop to be `ARRIVED`, but arriving moves that stop's `SCHEDULED` appointments to `IN_PROGRESS`. Both preconditions stated as written; the tension named, not resolved.
3. **§3.8 — turnaround hold.** The transition admits `ACQUIRED`, `ASSIGNED`, `READ_IN_PROGRESS`, `PRELIM_REPORTED`; rung 3 requires the actor to hold an `ACCEPTED` assignment, which only exists in the last two. Both stated.
4. **§3.2 — missing `clinical_history` on referral accept** has no nominated error code; rendered as either `ERR_VALIDATION` or `ERR_REFERRAL_INVALID_STATE`.
5. **§3.8 — `clinical_history` on resume** is declared as a request field with no declared effect; rendered as either recorded or accepted-and-discarded.
6. **§3.9 — pricing view with no `ACTIVE` contract.** `ERR_CONTRACT_NOT_ACTIVE` is attached to posting only; the read-only pricing view's behaviour is left open rather than invented.
7. **§3.1 — block top-up scope.** Rung 16 is phrased as a property of the *clinic*; on a top-up it admits "clinic has exactly one active contract" or "the targeted contract must itself be active". Both stated.
8. **§3.5 — `NON_DIAGNOSTIC` cascade asymmetry.** The four-hop trip-share re-allocation is enumerated only under the `REPEAT_REQUIRED` branch, though both branches move the study into `REPEAT_PENDING`. Rendered as attached to the state move, with the scaffold's asymmetry flagged in the text.
9. **§3.4 — depart precondition code.** "No study under the stop's appointments may still be `ORDERED`" has no dedicated error; routed to `ERR_STOP_INVALID_STATE` (rung 17) with the gap named explicitly.

### Scaffold self-contradictions found
- **Trip share on cancel** (item 1 above) — a direct contradiction between `endpoints[].side_effects` and the `state_machines` transition note. Carried forward, not resolved.
- **No-show vs arrive fan-out** (item 2) — mutually exclusive preconditions absent an appointment booked after arrival.
- **Image-QC ownership.** `complexity_profile.role_model` states "the FieldTech who acquired a Study is the only actor who may run its image QC"; ladder rung 3 states "`POST /studies/{study_id}/qc` carries NO ownership clause: any active FieldTech may record an image-quality verdict, including on a TELERAD study that no technician ever touched." Adopted the rung-3 text (normative rule table, explicitly exhaustive) and reported the header annotation rather than weakening the rule in prose.
- **Equipment `FAIL` from `UNCALIBRATED`.** The state machine declares `VALID → QUARANTINED` and `EXPIRED → QUARANTINED` only, but the computed `calibration_status` definition makes any non-null `quarantined_at` yield `QUARANTINED` regardless of prior state. The computed definition is stated in full in §3.1, which covers the case; no invention needed.
- **Rung 40 limb (a)** tests the *payload's* `service_minutes` even though the STAT override to 30 is declared to apply "before this rung and every later rung runs". Transcribed verbatim with the consequence spelled out (a STAT stop asking for 10 minutes is still rejected).

### Orchestrator independent verification
- `workspace/PRD.md` = 605 lines / 18,232 words.
- Leakage probe for `test_recipe` / `scaffold_difficulty_design` / `scaffold_corner_design` in PRD.md → **0 hits**.
- Independent re-derivation from SCAFFOLD.yaml: **87/87 endpoint paths** and **74/74 error ids** literally present in PRD.md, 0 missing.

## Step 5: Generate unit tests — 2026-08-09T06:32:00.000Z

(Launched concurrently with Step 6 in a single assistant message, so `test_suite/` did not exist on disk when impl-gen started.)

Test infrastructure and suite are complete and audited.

### Files written

**`test_helpers/`** (2,286 lines): `__init__.py` 37 · `types.py` 548 · `api_client.py` 379 (one method per PRD endpoint) · `api_errors.py` 161 (74 error ids + HTTP map, registered with the framework) · `assertions.py` 308 · `constants.py` 67 · `factories.py` 160 · `test_users.py` 55 · `fixtures.py` 571

**`test_suite/`** (4,898 lines): `conftest.py` 40 · `test_01_reference_data_and_access.py` 562 · `test_02_routes_and_stops.py` 660 · `test_03_referrals_and_appointments.py` 341 · `test_04_acquisition_and_equipment_qc.py` 566 · `test_05_reading_and_reporting.py` 381 · `test_06_reports_and_peer_review.py` 458 · `test_07_turnaround_clock.py` 293 · `test_08_pricing_and_trip_shares.py` 522 · `test_09_cascades_and_conservation.py` 543 · `test_10_billing_gates_and_repeats.py` 529

### Counts

126 `def test_` functions (142 collected cases after two parametrized families) — **58 queue-A** (Difficulty) + **68 queue-B** (Corner). Every one of the 20 difficulty instances has ≥2 tests; every one of the 59 non-stub corner instances has ≥1. **0 instances skipped.** The 5 `excluded_because:` stubs were not translated and all 5 `difficulty_instance` cross-references resolve.

### Friction cross-check

| # | Verdict |
|---|---|
| 1 — cancel/not-perform ORDERED study moves sibling shares? | **AVOIDED.** No test asserts a sibling's `trip_share_cents`, `version` or `updated_at` after an ORDERED study leaves. Note the readings coincide *numerically* anyway (an ORDERED study was never in the billable set, so "recompute" is a no-op); they differ only in whether sibling records are touched, which nothing asserts. |
| 2 — no-show reachability | **AVOIDED.** The no-show probe drives the stop to `ARRIVED` and cancels the appointment from `IN_PROGRESS`, so the appointment's status is the only failing precondition and `ERR_APPOINTMENT_INVALID_STATE` is forced. |
| 3 — turnaround hold: workflow precondition vs rung-3 ownership | **AVOIDED.** Both hold tests hold from `READ_IN_PROGRESS` with an `ACCEPTED` assignment — admissible under both readings. |
| 4 — missing `clinical_history` on accept | **NOT-REACHED-BY-ANY-TEST.** Every accept in the suite runs against a referral that already carries history. |
| 5 — `clinical_history` on resume | **OMITTED-ASSERTION.** The field is supplied verbatim where the design pins it, but nothing asserts it was recorded or discarded. |
| 6 — pricing view with no `ACTIVE` contract | **AVOIDED.** All 12 `GET /studies/{id}/pricing` calls run against a clinic holding exactly one `ACTIVE` contract. |
| 7 — block top-up scope | **AGREEMENT-BY-CONSTRUCTION.** Every top-up targets a clinic holding exactly one contract, and that contract computes `ACTIVE` (window 2026-05-01→2026-08-01, clock 2026-05-04). "The clinic has exactly one active contract" and "the targeted contract is the active one" are the same proposition when there is only one contract and it is active — both readings admit the write and both refuse nothing. |
| 8 — `NON_DIAGNOSTIC` cascade asymmetry | **AGREEMENT-BY-CONSTRUCTION.** The `NON_DIAGNOSTIC` test uses a stop with exactly one study. Reading A (cascade runs): survivors = billable-set members other than the leaver = ∅, so the re-allocation writes nothing. Reading B (cascade attaches only to `REPEAT_REQUIRED`): nothing runs. Both yield the same observables, and the leaver's own share is 0 either way because it is derived from set membership (§2.11), not from the cascade. The sibling-rise test deliberately uses the `REPEAT_REQUIRED` branch the scaffold does enumerate. |
| 9 — depart with a study still `ORDERED` | **NOT-REACHED-BY-ANY-TEST.** Every depart happens with zero `ORDERED` studies under the stop; no test asserts the refusal. |

### Near-miss register — which tests are fair only by accident

| Test | Friction next door | One edit that makes it unfair | Distance |
|---|---|---|---|
| `test_the_survivors_trip_share_rises_when_a_sibling_leaves_the_billable_set` (08) | 8 | Change the literal `"REPEAT_REQUIRED"` to `"NON_DIAGNOSTIC"` — the four-hop re-allocation is then exactly the un-enumerated branch. | **1** (closest) |
| `test_no_showing_an_already_cancelled_appointment_...` (03) | 2 | Flip the scene's `dispatch`/`arrive` to False — two preconditions then fail at once and `ERR_STOP_INVALID_STATE` vs `ERR_APPOINTMENT_INVALID_STATE` reopens. | **1** |
| `test_holding_the_clock_...` / `test_the_elapsed_partition_survives_...` (07) | 3 | Drop the `accept_read` call from `_study_read_in_progress_at_ten` and hold from `ACQUIRED`. | **1** |
| `test_a_second_block_top_up_...` (10), `test_the_block_partition_holds_...` (09) | 7 | Add one more contract for the same clinic — "clinic has exactly one active" and "targeted one is active" then diverge. | **1** |
| `test_posting_a_study_belonging_to_another_clinic_is_a_scope_mismatch` (10) | *(new, see below)* | Change the foreign clinic's `valid_until` to a past date — `ERR_CONTRACT_NOT_ACTIVE` vs `ERR_CLINIC_MISMATCH` becomes reading-dependent. | **1** |
| `test_a_stop_whose_billable_set_empties_...` (08) | 8 | Add one sibling study at the stop **and** assert its re-priced share. | 2 |
| `test_resuming_a_study_whose_clock_is_not_paused_is_refused` (06) | 5 | Pause the clock first **and** assert the resumed study echoes `clinical_history`. | 2 |
| `test_the_appointments_four_disposition_counters_partition_its_total` (03) | 1 | Add a second acquired sibling **and** assert its `trip_share_cents`/`version` after the not-performed marking. | 2 |
| `test_the_cancellation_lead_time_tiers_...` (08) | 1 | Acquire a sibling at the stop **and** assert its `version` bumped by the cancellations. | 2 |

### Disagreements found between a design-index `expect:` and the PRD derivation

Three; in each case the single contested assertion was **omitted** and the rest of the instance kept:

1. `Corner/calculations/stop_with_zero_billable_studies_allocates_no_trip_fee_at_all` asserts `post_total == 26000`. PRD §3.9 step 5–6 gives base 26000 + trip 0 + surcharge 0 + admin `round_half_up(0.03 × 26000) = 780` → **26780**. (The sibling corner instance `telerad_study_never_carries_a_trip_share` independently pins 26780 for the same shape, confirming the index dropped the admin fee here.) `total_price_cents` is not asserted; `billable_studies_at_stop == 0` and `trip_share_cents == 0` are.
2. `Corner/state_machines/completed_route_freezes_every_later_stop_write` asserts `actual_occupied_minutes == 10`. Arrival 08:00 → departure 09:25 is 85 whole minutes, so §3.3 gives 10 drive + 85 = **95**. Neither number is pinned; the test asserts `ERR_ROUTE_FROZEN`, `COMPLETED`, `completed_at != null` and the stop's `SERVICED`.
3. `Corner/errors/acquisition_matching_sweep_isolates_each_rung_in_ladder_order`, fourth trigger, expects `ERR_EQUIPMENT_NOT_ON_UNIT` while naming `t_xr` — a RADIOGRAPHY-only technician — on an ULTRASOUND study, which rung 23's certification limb pre-empts long before rung 26. Rather than pin an unreachable outcome, rung 26 was built correctly in the same test: a second van, staffed by an ULTRASOUND-certified on-route technician at an `ARRIVED` stop, acquiring with equipment bolted to the *other* van.

Also reported, not a design/PRD-derivation conflict but a **new ambiguity found and routed around**: PRD §2.8 rung 16 / §3.9 step 1 do not say whose contract is checked when posting — the invoice's clinic or the study's clinic. The corner index's mismatch probe (post clinic X's study to clinic Y's invoice, where X's contract is EXPIRED) is reading-dependent, so a third clinic with its own `ACTIVE` contract was introduced to make rung 16 pass under either reading before rung 47a fires.

### Two other fairness repairs
- Three studies created at the *same* logical instant made "the leftover cents go to the earliest-created members" depend on an unspecified tie-break. The trip-fee-split fixture now advances the clock between study creations (`study_clock_instants`), and the equipment-listing test does the same, so `created_at` ascending is a total order.
- Block-ledger assertions now select rows by `reason` rather than by list position, since the `DRAW` and `REFUND_QC` entries can share a `created_at`.

### Confirmations
- `def test_` count **126** == `Design:` tag count **126**; zero untagged, zero dual-tagged, zero tags pointing at a non-existent instance.
- **Zero** `pytest.mark.skip` / `skipif` / `xfail` markers anywhere in `test_suite/` or `test_helpers/`.
- All **248** docstring quotations survive a literal whitespace-normalized grep of `workspace/PRD.md`.
- Every instant assertion routes through `assert_same_instant`, which parses both sides (`Z`, `+00:00`, any fractional-second precision) and compares instants — never bytes.
- `test_helpers` imports cleanly; pyflakes is clean; pytest collects 142 cases. The implementation directory was never read, globbed or listed.

## Step 6: Generate implementation — 2026-08-09T06:32:00.000Z

(Launched concurrently with Step 5 in a single assistant message.)

Implementation complete at `workspace/implementation/`.

### Modules (5065 lines total incl. `start.sh`/`requirements.txt`)

| Layer | Files (lines) |
|---|---|
| entry | `app.py` 110, `start.sh` 12, `requirements.txt` 1 |
| core | `validate.py` 250, `constants.py` 116, `clock.py` 112, `errors.py` 109, `db.py` 103, `gates.py` 69, `envelope.py` 46, `ids.py` 39, `auth.py` 32 |
| services | `serialize.py` 413, `derive.py` 307, `pricing.py` 263, `cascades.py` 246, `tat.py` 115, `timecalc.py` 91, `notify.py` 24 |
| routes | `studies.py` 524, `reading.py` 513, `routing.py` 449, `reference.py` 420, `intake.py` 334, `billing.py` 288, `common.py` 79 |

### Endpoint-completeness gate
**declared 87 / routed 87 / MISSING 0 / EXTRA 0.** Only extra rule is Flask's built-in `GET /static/<path:filename>`. Verified programmatically by parsing `SCAFFOLD.endpoints[]`, booting in-process, dumping `app.url_map` and diffing normalized `{}` path params.

### Timestamp policy (one renderer: `core/clock.render`) — HTTP-verified on a live boot
- **(i) server-minted** → `YYYY-MM-DDTHH:MM:SS.mmmZ`, always 3 digits. `created_at` → `2026-05-01T00:00:00.000Z`.
- **(ii) caller-supplied** → parsed to an aware datetime, **consistently re-rendered** through the same function (PRD §2.4 licenses instant-equality). POSTed `"2026-04-01T00:00:00Z"` (plain Z, no fraction) reads back `"2026-04-01T00:00:00.000Z"`; `".000Z"` and `"+00:00"` forms render identically; `/_clock/set_current_utc` echoes `current_utc` the same way.
- **(iii) derived** → same renderer (`tat_deadline_at` → `2026-05-04T13:00:00.000Z`).
- Plain calendar dates (`service_date`, `period_start/end`) are **not** instants and echo verbatim. Real wall-clock time is never read anywhere.

### Enum routing — closed iff-list (documented in `core/validate.py`)
All **21** members HTTP-verified → `ERR_INVALID_ENUM` (400): clinic `status`; `billing_hold_status`; contract `kind`; unit `service_status` (create + action); equipment `modality`; `certified_modalities[]`; `modality_privileges[]`; `species_privileges[]`; specialist `status`; `stop_priority`; referral `species`/`study_kind`/`requested_modality`/`priority`; study `modality`/`hold_reason`/`repeat_cause`; `qc_result`; qc-check `result`; report `kind`. **No other field routes here.**

Deliberate exclusions, each HTTP-verified with its actual code: query filters (never error, return empty page); numeric ranges (`limit`, `offset`, minute-of-day, `score`, calibration span) → `ERR_VALIDATION`; wrong-state → the rung 17–22 state codes; body FKs → rung-4 404s; free-text type errors and malformed dates → `ERR_VALIDATION`.

### EADDRINUSE self-verification
Socket created by hand, `SO_REUSEADDR`, bounded retry (24 × 0.25 s = 6 s ceiling, then hard `sys.exit(1)`), served via `make_server(..., fd=sock.fileno())`.
- **Squatter test:** real process held the port 3 s; the server bound and answered at ~2.98 s — **1 success, 0 failures**.
- **14-cycle tight kill/relaunch loop: 0 start failures, 0 orphan processes, 0 stale listeners.**

### The 9 friction adjudications (governing principle: maximize reachable declared behaviour)
1. **§3.9 cancel/trip-share** — *re-derive the billable set from scratch*. Provably a no-op on siblings (the set begins at `ACQUIRED`; an `ORDERED` study was never a member), so this single choice satisfies **both** readings. Applied identically to not-performed and clinic-side appointment cancel.
2. **§3.4 no-show reachability** — *keep both preconditions as written*. NO_SHOW stays reachable by booking an appointment after the stop arrived (HTTP-verified). Both limbs report `ERR_APPOINTMENT_INVALID_STATE` because rung 17 is declared for route/route-stop action endpoints only.
3. **§3.8 hold** — *enforce both* the narrow rung-3 ownership (ACCEPTED assignment) and the wider workflow precondition. Keeps `ERR_NOT_RESOURCE_OWNER` reachable on `/hold` and the hold itself reachable (an ACCEPTED assignment exists exactly in `READ_IN_PROGRESS`/`PRELIM_REPORTED`).
4. **§3.2 missing `clinical_history` on accept** — `ERR_REFERRAL_INVALID_STATE` (rung 18, second limb). A rung-5 `ERR_VALIDATION` would fire on a stored field and pre-empt rungs 6–17 (notably `ERR_CLINIC_INACTIVE`) for every history-less referral.
5. **§3.8 `clinical_history` on resume** — *accepted, type-checked, discarded*. Nothing reads a recorded value; writing it to the Referral would mutate an unnamed record and bump its `version`.
6. **§3.9 pricing view with no ACTIVE contract** — *the read-only view answers, never fails*; falls to the `LIST_PRICE` branch. Raising `ERR_CONTRACT_NOT_ACTIVE` would strand the whole endpoint for contract-less clinics; the code stays reachable via posting.
7. **§3.1 block top-up scope** — *clinic-scoped, exactly as rung 16 is phrased*. Admits more top-up targets, strands nothing, and keeps the error reachable (0 or ≥2 active contracts).
8. **§3.5 NON_DIAGNOSTIC asymmetry** — cascade attached to the **move into `REPEAT_PENDING`**, so both branches re-allocate. Branch-specific attachment would break `INV_MONEY_INVOICE_TOTAL` on the NON_DIAGNOSTIC branch.
9. **§3.4 depart precondition** — `ERR_STOP_INVALID_STATE` under rung 17, the reading PRD §3.4 states outright.

**Four additional ambiguities found and adjudicated the same way** (comments at each site): billing-hold repeat-value write is idempotent (no code is licensed for the violation); `qc_status != PENDING_QC` on `/qc` → `ERR_STUDY_INVALID_STATE` (rung 19); stop `SERVICED` on `/studies/{id}/cancel` → `ERR_STUDY_INVALID_STATE`; resume from a `BREACHED`-with-open-pause study is refused, since rung 20 is explicit and exhaustive.

### Reachability claims — **hypotheses, to be verified by reading the code**
- **H1:** With friction 3 adjudicated as "enforce both", rung 19's `ERR_STUDY_INVALID_STATE` on `POST /studies/{id}/hold` may be unreachable (a study with an ACCEPTED assignment appears to sit only in `READ_IN_PROGRESS`/`PRELIM_REPORTED`, both admitted). The code itself is amply reachable on other study verbs.
- **H2:** G1's refusal of the **stop-bump** cascade may be unreachable, because hop-3 studies are `ORDERED` and an `ORDERED` study can never have been posted. The guard is implemented anyway. G1 on the **qc-check FAIL** path is definitely reachable (HTTP-verified).
- **H3:** PRD §3.8's "stays BREACHED after the clinic eventually resumes" may be unreachable given rung 20's literal `PAUSED` requirement (see adjudication above).

### Storage
Plain in-memory Python dicts only — audited: no sqlite/pickle/shelve/redis/ORM, no file I/O, no `/tmp`, no `seed_*`. Every collection is `{}` at import; no row is created outside a declared endpoint. Ids are **UUID-shaped with a monotonic counter in the high 32 bits** so ascending id == creation order (list ties at the coarse logical clock resolve deterministically) — this is id minting, **not** seeded data.

### Behavioural verification (4 suites, ~170 assertions, all green)
Round 1 full happy path + 7-hop quarantine cascade; Round 2 STAT bump 6-hop cascade, 3-way split `[4167,4167,4166]`, gates G1–G5, business-hours TAT (240 does not breach / 241 does), non-monotone escalation breach, cancellation tiers, G1 refusing a safety recall; Round 3 reading loops/caps, reporting chain + strict 14-day addendum window, peer review, repeats, hold/resume, geometry conflicts, block boundary, OCC, pagination; verify2 confirms **hop 4c** in-place re-pricing (survivor's trip share 6250→12500, admin fee 728→915, invoice total **rose** 24978→31415) and all six conservation invariants.

**Two genuine bugs were found and fixed during verification:** (a) `tat_status` was consulted before the read-time breach test, letting a hold succeed on a silently-breached study — the breach test now runs whenever a Study is loaded; (b) a posted study's `base_price_cents` drifted off its own `STUDY_READ` line once the next study drew the block down — the billed basis is now pinned at posting (the trigger list names only the pricing view and posting, never every read).

### Orchestrator independent verification of Steps 5+6
- **Isolation held both ways:** `grep -rIl "test_suite\|test_helpers" implementation/` → empty; `grep -rIl "workspace/implementation\|from implementation\|import app" test_suite/ test_helpers/` → empty; design-index leakage probe into `implementation/` → empty.
- 126 `def test_` == 126 `Design:` tags; 0 `skip`/`xfail`/`skipif`.
- Persistence probe on `implementation/*.py` for `sqlite|json.dump|pickle|/tmp/|datetime.now|utcnow|time.time()` → single hit is a **disclaiming doc comment** at `core/db.py:3`.
- **Independent route diff** (scaffold `endpoints[]` vs in-process `app.url_map`, compared as method+path pairs with params normalized): **87 declared / 87 routed / 0 MISSING / 0 EXTRA**, confirming Step 6's own gate. (A path-only comparison collapses to 76/76 because 11 paths carry two methods — method+path is the correct granularity.)
- `workspace/sweep.sh` pre-staged (2 waves of 4, `SWEEP_DONE` marker, no inline `pkill`).

## Step 7: Run tests and iterate — 2026-08-09T07:12:00.000Z

All 8 rounds green.

### Iterations
**2 sweeps.** Sweep 1: 141/142 in all 8 rounds (one deterministic failure). Sweep 2 after the fix: **142/142 × 8 rounds**.

### Tests deleted
**None.** The single failure was a repairable assertion bug, not PRD silence.

### Fixes applied to `test_suite/`
| File | Test | Why |
|---|---|---|
| `test_02_routes_and_stops.py` | `test_arriving_at_a_stop_before_the_route_is_dispatched_is_refused` → renamed `test_arrive_checks_the_route_state_before_the_stop_state` | Asserted `ERR_STOP_INVALID_STATE` on a scenario where **both** rung-17 limbs fail. PRD §2.8 rung 17 states verbatim: *"Internal order: the route is checked before its stop."* Route was `PUBLISHED` (arrive admits only `DISPATCHED`) and stop `PLANNED`, so the route limb must win. Repaired to assert `ERR_ROUTE_INVALID_STATE`, then **extended in the same test** to dispatch → arrive → arrive-again, isolating the stop limb (`ARRIVED` is not a from-state of `EN_ROUTE → ARRIVED`) so `ERR_STOP_INVALID_STATE` — which had exactly one claimant suite-wide — keeps its coverage. Both docstring quotes verified verbatim against PRD (whitespace-normalized). |

No `test_helpers/` fixes and **no `implementation/` fixes** were needed — the implementation was PRD-faithful on the one failure. This was a **fourth** design-index-vs-PRD numeric/logical disagreement, beyond the three the test generator flagged.

### CLEAN-SWEEP PROTOCOL

**A. Mechanical — PASS.** All 8 `results.N.json` parse; each has 142 individual rows, `passed==142`, `failed==0`, status set exactly `{'passed'}`; sorted test-name SHA256 identical across all 8 (`9a164d24cba7c393`). `def test_` = 126, of which 2 are parametrized (11 + 7 cases) → 124 + 18 = **142 = collected count**. Zero `pytest.mark.skip/skipif/xfail` (the only `skip` string hits are the word "skips" in test names). Persistence probe over `implementation/*.py` for `sqlite|json.dump|pickle|/tmp/|datetime.now|utcnow|time.time()|open(` → one hit, the disclaiming doc comment at `core/db.py:3`. Each `round.N.log` contains `Killed` **exactly once**, at line 19, on the first test, immediately followed by `PASSED`.

**B. Positive proof of per-test reset — PASS (two independent proofs).**
1. **Falsification experiment.** Re-ran the whole suite under `--isolation none` (one shared server). Exactly one test flips to failing: `test_the_logical_clock_starts_at_the_declared_default_instant` — `expected '2026-05-01T00:00:00Z' but got '2026-05-04T09:00:00.000Z'`. That test asserts a **process-global singleton** and cannot pass after any earlier test has moved the clock. It passes in all 8 sweep rounds ⇒ a genuinely fresh process served it every time.
2. **Id-space restart.** `core/ids.py` mints ids from a boot-local monotonic counter. Two independent boots each returned **byte-identical** first ids for the first two clinics (`00000001-0000-4001-8001-000000000001`, `00000002-...0002`). An id space that restarts at 1 is direct evidence the row store was empty at boot.
3. **Shared-literal uniqueness claim.** The domain's one global uniqueness rule is rung 42 (*"a clinic may host at most one counted route stop per `service_date`… across every route and every mobile unit"*). Because the counter restarts, **13 tests across 4 files** (`test_02`, `test_03`, `test_04`, `test_09`) each successfully claim the same literal key `(00000001-0000-4001-8001-000000000001, "2026-05-04")`. Caveat stated honestly: its falsification mode is weaker than the template assumes — under a shared server ids would keep advancing rather than colliding, so this corroborates (1)+(2) rather than standing alone. **Finding worth recording: this suite is unusually reset-tolerant (1/142 reset-sensitive) because every key is a minted id.**

**C. Friction cross-check — 9/9, zero DEPENDS.**

| # | Verdict | Evidence re-derived |
|---|---|---|
| 1 cancel/not-perform sibling shares | **CLEAN** | No test asserts a sibling's `trip_share_cents`/`version`/`updated_at` after an `ORDERED` study leaves. Cancellation-tier tests assert only each leaver's own fee/`billing_status`; the disposition-counter test asserts counters only. |
| 2 no-show reachability | **CLEAN** | Scene uses `arrive=True`, so the stop **is** `ARRIVED` and the appointment was cancelled from `IN_PROGRESS`. Only the appointment-status precondition fails → `ERR_APPOINTMENT_INVALID_STATE` forced under both readings. |
| 3 turnaround hold | **CLEAN** | Both hold tests use `offer_and_accept_read`, so the study is `READ_IN_PROGRESS` with an `ACCEPTED` assignment held by the acting specialist — admissible under ownership-only, workflow-only, and both. |
| 4 missing `clinical_history` on accept | **CLEAN (not reached)** | The only null-history referral (`_referral_without_history`) is always resubmitted with a history before any `accept_referral`. |
| 5 `clinical_history` on resume | **CLEAN (omitted assertion)** | Supplied at 3 resume sites; nothing asserts it was recorded or discarded. Asserted fields are `tat_status`, `pause_started_at`, `hold_reason`, TAT partition — all invariant under both readings. |
| 6 pricing view, no `ACTIVE` contract | **CLEAN** | All **13** `get_study_pricing` calls audited: every scene creates exactly one contract, `2026-05-01 → 2026-08-01`, clock `2026-05-04` ⇒ `ACTIVE`. |
| 7 block top-up scope | **AGREEMENT-BY-CONSTRUCTION (re-derived)** | Both top-up tests: clinic holds exactly one contract and it computes `ACTIVE`, so \|actives\|==1 **and** target ∈ actives — the two readings are the same proposition here. |
| 8 `NON_DIAGNOSTIC` cascade asymmetry | **CLEAN — stronger than claimed** | Re-derived rather than accepting "agreement-by-construction": `trip_share_cents` and `billable_studies_at_stop` are **derived on read** from the billable set (`services/pricing.py`); the cascade only mutates persisted **charge lines**. And a posted study can never receive an image-QC verdict (`/qc` requires `ACQUIRED`, posting requires `FINALIZED`), so friction 8's persisted-line limb is **untestable by construction**. Both readings are observationally identical suite-wide. |
| 9 depart with a study still `ORDERED` | **CLEAN (not reached)** | All 4 departs audited: `test_03`'s runs after one acquire + one not-performed (pending == 0); `test_02`'s three run on stops with no appointments at all. |

**D. Near-miss register — 9 verified, 2 corrected, 1 observation added.**

Confirmed at **distance 1**: the no-show test (F2 — flip `arrive` to False and both preconditions fail at once); both hold tests (F3 — drop `accept_read` and hold from `ACQUIRED`); both top-up tests (F7 — add a second contract for the clinic); `test_posting_a_study_belonging_to_another_clinic_is_a_scope_mismatch` (rung-16 "whose contract?" ambiguity — expire the foreign clinic's contract and `ERR_CONTRACT_NOT_ACTIVE` vs `ERR_CLINIC_MISMATCH` reopens; the third-clinic construction is what defuses it).

Confirmed at **distance 2**: the disposition-counter test and the cancellation-tier test (F1 — note the discriminator is the sibling's `version`/`updated_at`, **not** its `trip_share_cents`, which is numerically identical under both readings).

**Corrections to the generator's register:**
- `test_the_survivors_trip_share_rises_...` was listed as the **closest** entry (distance 1, F8). **Refuted** — swapping `REPEAT_REQUIRED`→`NON_DIAGNOSTIC` would *not* make it unfair, because it asserts only derived-on-read pricing-view fields and posts nothing. The real distance-1 edit would require posting the survivor first and asserting its `ACTIVE TRIP_FEE_SHARE` line amount — which is unreachable (see C-8). Effective distance: unreachable.
- `test_a_stop_whose_billable_set_empties_...` (listed distance 2, F8): same correction, for the same reason.
- `test_resuming_a_study_whose_clock_is_not_paused_is_refused` (F5, distance 2): the stated edit ("assert the resumed study echoes `clinical_history`") would fail under *both* readings — Study carries no such field. The genuine discriminating edit is to pause first, resume, then GET the parent **Referral** and assert its `clinical_history` moved.
- **Added observation (not a fairness risk):** `test_the_cancellation_lead_time_tiers_...` depends on `dispatch=False`. With `dispatch=True` the fee moves onto §3.9's DISPATCHED branch (percentage-of-list **plus** the whole 12500 trip fee once no `ORDERED` sibling remains). Both branches are fully PRD-determined, so this is brittleness, not unfairness.

**E. Assertion provenance — PASS.** 104 distinct asserted `["field"]` names extracted; **99 appear verbatim in PRD.md**, the 5 residuals are test-local scene-dict keys (`second_equipment`, `total_before`, …). Numerics re-derived by hand: `[4167,4167,4166]` (12500//3=4166, remainder 2 → earliest two get +1, sums to 12500); `33218` (26000+6250+⌈967.5⌋=968); `39655` (38500+1155); `44290` (43000+1290); `27038` (26250+787.5→788); `31072`/`31071` with **both** admin fees landing on 905 (905.01 and 904.98), so the one-cent share difference carries through exactly as the docstring claims; cancellation tiers 0 / 13000 / 26000 at leads 1440 / 1439 / 239; TAT 180 = 120 + 60. Zero bytewise instant comparisons — every instant assertion routes through `assert_same_instant`, which parses both sides. Every asserted list index is either guarded by `len(rows)==1` or traces to PRD §2.3 *"List results are ordered by `created_at` ascending"*, with fixtures advancing the clock between creations to make that a total order.

### Hypothesis verdicts
- **H1 — CONFIRMED (unreachable).** `routes/studies.py:387` runs `require_owner(bool(accepted))` — an `ACCEPTED` assignment held by the actor — **before** the rung-19 gate at line 412. Every writer of `read_assignments.status` traced: `accept` (`reading.py:111`) sets `ACCEPTED` and moves the study `ASSIGNED → READ_IN_PROGRESS`; FINAL publication (`reading.py:296-303`) sets the study `FINALIZED` **and** flips every `ACCEPTED` assignment to `COMPLETED` in the same transaction; hand-back requires `ACCEPTED` and returns the study to `ACQUIRED`; the quarantine cascade (`cascades.py:101-106`) `REVOKE`s every `OFFERED`/`ACCEPTED` assignment as it moves the study to `REPEAT_PENDING`. So an `ACCEPTED` assignment exists **exactly** while the study is `READ_IN_PROGRESS` or `PRELIM_REPORTED` — both admitted by the gate. `ERR_STUDY_INVALID_STATE` on `POST /studies/{id}/hold` cannot fire.
- **H2 — CONFIRMED (unreachable on the stop-bump path).** `cascades.guard_provider_cancel_gate_g1` (line 237) collects **only** studies whose `workflow_status == "ORDERED"`. `billing.py:82-128` shows an `ORDERED` study is unpostable: rung 48 demands `FINALIZED` unless `fee_only`, and `fee_only` requires `cancellation_fee_cents > 0`, which is written only by `cancel`/`not-performed`/no-show — all of which move the study **out of** `ORDERED`. No path returns a study to `ORDERED`, so no `ORDERED` study can own a charge line and `g1_no_frozen_lines` can never fire from that call site. The qc-check FAIL path is a different call site (`blast_radius` admits `FINALIZED`/`POSTED` studies) and **is** reachable — exercised by `test_the_surviving_study_is_re_priced_upwards_while_its_sibling_is_reversed`.
- **H3 — CONFIRMED (unreachable).** `resume_study` (`studies.py:442`) requires `tat_status == "PAUSED"` verbatim, and `tat.mark_breached` (`tat.py:81`) **overwrites** `tat_status` with `"BREACHED"`, destroying the `PAUSED` value. So a study that breaches mid-pause (reachable — a STAT escalation re-anchors and re-targets, and `escalate-stat` calls `tat.evaluate`) can never be resumed: the resume returns `ERR_TAT_CLOCK_STATE_INVALID`. PRD §3.8's "stays `BREACHED` after the clinic eventually resumes" has no reachable witness.

### Orchestrator independent verification
- All 8 `results.N.json` re-parsed from disk: **142 individual rows each**, `passed=142 failed=0`, status set exactly `{'passed'}`, sorted-name SHA256 `9a164d24cba7c393` **identical across all 8 rounds**.
- `find implementation test_suite test_helpers -newer results.1.json` (`.py`/`.sh`) → **empty**, proving the final sweep post-dates every edit.
- Per-round logs: `Killed` exactly once, `Traceback` zero, in all 8 rounds.

## Step 8: Finalize PRD — 2026-08-09T07:20:00.000Z

(Not skipped: Step 7 applied 1 `test_suite/` fix, so the zero-fix skip condition did not hold.)

`PRD_FINALIZED.md` written with two minimal edits, both traced to `<step_7_diff>` items.

### Line counts
`PRD.md` 605 lines / `PRD_FINALIZED.md` 605 lines — **0.0% line delta** (both edits are in-paragraph revisions; 2 of 605 lines changed, +~90 words).

### Changes (2)
- **§3.8 "Holding the clock"** — *revise* — replaced the explicit non-adjudication ("this document does not adjudicate between the wider workflow precondition and the narrower ownership rule") with the choice the implementation made: **both** rules are enforced, each at its own ladder rung, rung-3 ownership before rung-19 workflow, so a specialist with no `ACCEPTED` assignment gets `ERR_NOT_RESOURCE_OWNER` regardless of `workflow_status`. — `routes/studies.py:387` (`require_owner(bool(accepted))`) then `routes/studies.py:412` (`_study_state_gate`). Traces to **H1**.
- **§3.8 final paragraph (escalation while paused)** — *revise* — the clause "`pause_started_at` is retained so the study stays `BREACHED` after the clinic eventually resumes" asserted a resume the implementation refuses. Now: `pause_started_at` is retained rather than cleared, but the breach overwrites `PAUSED` on the `tat_status` axis, so the later resume fails rung 20 with `ERR_TAT_CLOCK_STATE_INVALID`; such a study stays `BREACHED` and is never resumed. — `services/tat.py:81` (`mark_breached` overwrites `tat_status`), `routes/studies.py:442` (resume requires `tat_status == "PAUSED"`). Traces to **H3**.

### Zero-edit items (3)
- **The one test fix (rung-17 route-before-stop ordering)** — pure test-fixture bug; PRD already governs verbatim, §2.8 rung 17: *"**Route and stop state preconditions** for the requested transition. Internal order: the route is checked before its stop. A route in a from-state that does not admit the transition raises `ERR_ROUTE_INVALID_STATE` (409); a stop in such a state raises `ERR_STOP_INVALID_STATE` (409). Applies to every route and route-stop action endpoint."* Confirmed against `routes/routing.py:391` (route `DISPATCHED` check) preceding `:393` (stop from-state check) on `/route-stops/{id}/arrive`.
- **H2 (G1 unreachable on the stop-bump path)** — no edit. The PRD states this leg conditionally, not as a reachable assertion, §3.4: *"If any of the charge lines reachable at hop 4 sits on an invoice that is already `FINALIZED`, gate G1 refuses the whole insertion with `ERR_INVOICE_FINALIZED` before anything is written."* Hop 4's scope is hop 3's studies (those in `ORDERED`), which is exactly the set `cascades.guard_provider_cancel_gate_g1` (line 237) collects — prose and code agree; the set is just provably empty. The reachable qc-check FAIL call site is separately and correctly governed by §2.9.
- **Test-suite deletions / helper fixes / implementation fixes** — none occurred, so nothing to adjudicate.

### Per-edit pre-edit search log

**Edit 1 — §3.8 hold preconditions**
- (a) Subject: the hold endpoint's precondition set and the order in which its ownership and workflow checks are evaluated.
- (b) Paths enumerated and read: `routes/studies.py:386-425` (whole `hold_study` body: `authenticate` → `authorize("Specialist")` → `need(...)` → `require_owner` → `body()`/`req_str`/`enum_value` → `_study_state_gate` → tat-axis gate); `routes/studies.py:31-36` (`_study_state_gate`, terminal limb before invalid-state limb); `core/auth.py:26` (`require_owner`); grepped every `require_owner` callsite repo-wide (routing.py 316/341/388/412, studies.py 40/55/159/407, intake.py 29/155/245/294, reading.py 108/127/150/262/322/355/494) to confirm no other endpoint carries the "ACCEPTED read assignment" flavour of rung 3; PRD §2.8 rungs 3, 5, 6, 19, 20 for ladder consistency.
- (c) Wording adjustment: originally drafted as "the ownership clause is evaluated first, the workflow precondition immediately after"; changed to "each is evaluated at its own rung of the single ladder — the rung-3 ownership clause before the rung-19 workflow precondition" so the sentence does not exclude the rung-5/6 `hold_reason` presence/type and enum checks the implementation genuinely runs in between. Deliberately made **no** reachability claim about `ERR_STUDY_INVALID_STATE` or `ERR_STUDY_TERMINAL` on this endpoint, since asserting unreachability would be a new universal claim beyond what the edit needs.

**Edit 2 — §3.8 escalation from a paused clock**
- (a) Subject: the `tat_status` axis leaving `PAUSED`, the lifecycle of `pause_started_at`, and the resume gate.
- (b) Paths enumerated and read: `services/tat.py` in full (`mark_breached` :74-90 — overwrites `tat_status`, never touches `pause_started_at`; `mark_met` :92-96; `evaluate` :99-105; `settle_on_final` :108-115; `paused_minutes` :39-46 — the open-window term is conditioned on `tat_status == "PAUSED"`; `_freeze` :68-71); `routes/studies.py:274-311` (`escalate_stat`, ending in `tat.evaluate`); `routes/studies.py:415-421` (hold sets `PAUSED` + `pause_started_at`); `routes/studies.py:442-453` (resume: `tat_status != "PAUSED"` → `ERR_TAT_CLOCK_STATE_INVALID`, then clears `pause_started_at`); `services/serialize.py:200,221` (read-time `tat.evaluate`, `pause_started_at` exposed); plus a repo-wide grep for every `pause_started_at`, `tat_status"] =`, `_pause_windows`, `tat.evaluate`, `settle_on_final`, `mark_met`, `mark_breached` callsite (`routes/common.py:23,41`; `routes/reading.py:118,141,170,304,312`; `routes/studies.py:128,207,228,268,312,357,379,452`) to confirm resume at `studies.py:448` is the **only** writer that clears `pause_started_at` and the only path back to `ACCRUING`.
- (c) Wording adjustment: dropped an earlier draft phrase ("the pause is over as far as the clock is concerned") because it could be read as a claim about how `tat_paused_minutes` behaves after the freeze — an area the edit has no business pinning. Kept the claim scoped to studies that breach **while held**, and said nothing about `mark_met`, which also overwrites `PAUSED` on the publish path.

### Orchestrator independent verification
- `PRD.md` 605 → `PRD_FINALIZED.md` 605 lines; `diff` reports exactly **4 changed lines** (2 revised in-paragraph pairs), consistent with the reported 2 edits.
- `diff` of all `^#` headings PRD.md vs PRD_FINALIZED.md → **empty** (no sections added).

## Step 9: Complete PRD — 2026-08-09T07:36:00.000Z

`PRD_COMPLETED.md` written at `workspace/PRD_COMPLETED.md`.

- **Line counts**: 605 → 606 (one new bullet in §2.2; every other edit is in-paragraph). **Char delta**: +15,407. 49 paragraphs revised, 1 added. Section headers (22) and endpoint/error table rows (165) unchanged.
- **53 inline edits**: **50 ambiguity-pins**, **3 mismatch-revisions**.

### Per-question yield
| Probe | Edits |
|---|---|
| Q1 unread / write-only fields | **14** |
| Q2 universal quantifiers | 3 |
| Q3 derived-on-read vs stored | 6 |
| Q4 response projections | 4 |
| Q5 list semantics | 2 (3 pins) |
| Q6 conditional cascade legs | 8 |
| Q7 version ledger | 5 |
| Q8 unenforced uniqueness/scope | 3 |
| Q9 error precedence | 7 |
| Q10 timestamps | 2 |

### The three mismatches
- **§3.1 — revise — mismatch** — "Placing a hold requires the clinic to be `CLEAR`, lifting one requires it to be `HOLD`" is enforced nowhere; the capability writes the supplied value and a no-op write still bumps `version` (`routes/reference.py:100-118`).
- **§2.11 — revise — mismatch** — "every affected record's `updated_at` is refreshed and its `version` incremented" fails for two movements: `tat_status` settling to `MET`/`BREACHED` (`services/tat.py:74-106`, no `db.touch`) and stop `sequence` renumbering (`services/derive.py:203`).
- **§3.9 step 2 — revise — mismatch** — base price is *not* derived on every read: posting pins `price_basis`/`base_price_cents` to the billed figures, on the study resource and the pricing view alike, until a re-post (`services/pricing.py:66-67`, `routes/billing.py:138-142`).

### Selected pins (abbreviated)
- §2.2 — insert — unknown path/method → `ERR_RECORD_NOT_FOUND` 404 (`app.py:51-61`); `api_request_id` = `req_` + 20 upper-alnum (`core/envelope.py:14`).
- §2.3 — insert — non-integer `limit`/`offset` → `ERR_VALIDATION`; created_at ties break on persistence order, never on `id`; filters compared as text and never error (`core/validate.py:221-249`, `core/db.py:102`, `routes/common.py:56-70`).
- §2.4/§2.5 — insert — client instants are re-rendered canonically, not echoed; `current_utc` likewise (`core/clock.py:57-70`, `routes/billing.py:287`).
- §2.8 rung 3 — insert — body-identity ownership clauses decide before rung 4; graph-walk clauses necessarily after (`routes/intake.py:27-31` vs `routes/studies.py:52-55`).
- §2.11 — insert — breach test runs over *every* `GET /studies` row before filtering, so a study can breach on a request that never returns it (`routes/studies.py:127-128`).
- §3.1 — insert — recalibration does not move `last_passing_qc_at`, so a later failure's blast radius is unchanged (`routes/reference.py:344-348`).
- §3.1 — insert — rung 16 on top-up is **clinic-scoped** as phrased (`routes/reference.py:200`).
- §3.2 — insert — missing `clinical_history` → `ERR_REFERRAL_INVALID_STATE`, after the from-state test (`routes/intake.py:109`).
- §3.3/§3.4 — insert — bump hop 2 also stamps the appointment's `cancel_reason`; a stop cancellation propagates its reason to appointments *and* studies (`services/cascades.py:162-179`).
- §3.4 — insert — no-show: both preconditions enforced, both `ERR_APPOINTMENT_INVALID_STATE`, appointment tested first (`routes/intake.py:308-314`).
- §3.5 — insert — a study in `ORDERED`/`CANCELLED`/`NOT_PERFORMED` always renders `price_basis` null and six money fields 0, while `GET /studies/{id}/pricing` computes the decomposition anyway (`services/serialize.py:196,236-258`).
- §3.6 — insert — hop 4b is conditional on a line actually reversing (so the study's version climbs by two only then); REFUND_QC matches draws one-for-one and its `balance_after_studies` is post-refund (`services/cascades.py:27-51`).
- §3.8 — insert — `hold_reason` and the resume `clinical_history` are both accepted and never consulted; resume has no workflow precondition (`routes/studies.py:440`).
- §3.9 — insert — the cancellation trip-share friction resolves by running the re-derivation and observing it is a no-op; the pricing view answers via `LIST_PRICE` when no single `ACTIVE` contract exists; re-pricing never creates or deletes lines; `posted_study_count` never freezes (`services/pricing.py:44-74,211-263`, `services/derive.py:283-290`).

### Deliberately not pinned
- The three Step-8 reachability findings (rung 19's `ERR_STUDY_INVALID_STATE` on `/hold`, G1 on the bump path, breach-mid-pause) — per instructions.
- Bump-cascade hops 4/5 being unreachable for the same reason G1 is there (an `ORDERED` study never owns a charge line) — same finding family as a pinned item.
- `depart` not testing the owning route's state, contra rung 17's "route before stop": unreachable, since a stop is `ARRIVED` only under a `DISPATCHED` route and unpublish is refused while any stop is `ARRIVED`.

### Orchestrator independent verification
- `PRD.md` 605 lines / 128,269 chars → `PRD_FINALIZED.md` 605 / 128,713 → `PRD_COMPLETED.md` 606 / 144,201 (**+15,932 chars end-to-end**).
- `diff` of all `^#` headings PRD.md vs PRD_COMPLETED.md → **empty**, proving Step 9 added no sections.
- `find implementation test_suite test_helpers -newer results.1.json` (`.py`/`.sh`) → **empty after Step 9 as well**, proving Steps 8 and 9 touched no code and the 142/142 × 8 result still describes the shipped tree.

---

# PIPELINE COMPLETE — task_0939_mobile_veterinary_diagnostics_imaging

**142/142 tests passing on all 8 sweep rounds. 0 tests deleted, 0 `test_helpers/` fixes, 0 `implementation/` fixes, 1 `test_suite/` repair.**

Scale: 19 entities · 87 endpoints · 74 error codes · 50-rung ladder · 37 calculations (10 dual-variant) · 15 state machines (15 non-linear) · 4 OCC rules · 6 conservation invariants · ordered G1–G5 write gates · 6-hop cascade · 40 declared constants (0 undeclared). PRD 605 lines / 18,232 words; implementation 5,065 lines / 24 modules; suite 126 test functions / 142 collected cases (58 queue-A + 68 queue-B, 0 instances skipped).






