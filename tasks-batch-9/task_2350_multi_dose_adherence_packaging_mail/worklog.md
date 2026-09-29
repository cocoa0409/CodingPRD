# Worklog — task_2350_multi_dose_adherence_packaging_mail

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2350_multi_dose_adherence_packaging_mail/` and `tasks/task_2350_multi_dose_adherence_packaging_mail/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T05:32:00.000Z

All three scaffold artifacts are complete in `/home/ubuntu/github/CodingPRD/tasks/task_2350_multi_dose_adherence_packaging_mail/`, generated only from the scenario text and the generator skill spec (no sibling task was read).

Linter verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2350_multi_dose_adherence_packaging_mail/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2350_multi_dose_adherence_packaging_mail/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2350_multi_dose_adherence_packaging_mail/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     12
  §1.8 instances scanned:     25
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1062

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

What was generated

- `SCAFFOLD.yaml` (§1.0–§1.7, 160 KB): domain `multi-dose-adherence-mail-pharmacy`, prefix `/pharmacy`. 12 entities, 8 state machines (parallel shape: `packaging_status` × `insurance_status` on FillCycle), 2 OCC concurrency rules, 8 calculations (3 with dual variants: sync bridge/trim, provisional/final copay, rolling/cycle-scoped adherence), 45 ordered validations, 53 endpoints (25 GET / 28 POST), 56 error codes, 6 roles with segregation of duties (`Patient` is `identity: entity_backed:Patient`). Complexity layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency; consistency `immediate`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): all 9 difficulty rules, 25 instances (2–4 per rule), each with structured `trigger:` call lists, `${var}` captures and pre-computed literal asserts.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): all 9 sections in guide order, 103 instances — entities 15, state_machines 16, calculations 13, validations 15, endpoints 8, errors 17, rbac 8, cross_cutting_complexity_layers 9, consistency_model 2. 31 of those are `excluded_because` stubs citing real §1.8 instances; 72 carry full recipes. All 126 instance names are unique across both design files, and every one of the 56 error ids is referenced.

Notable design findings worth flagging to whoever writes the PRD:

- `ERR_ROLL_NOT_VERIFIED` (priority 26) is not reachable through any legal sequence: a POUCH_ROLL parcel can only be staged from `VERIFIED`/`SHIPPED`, and every route that sends the roll back to the bench (regimen change) cancels that STAGED parcel first, so priority 14 answers instead. It is documented in the errors section as a shadowed defence-in-depth guard (`pouch_dispatch_roll_guard_is_shadowed_by_the_parcel_state_check`) with the ordering pinned by test, rather than given a fabricated recipe.
- Single-line reissues can legitimately produce a `CreditMemo` of `amount_cents 0` (gross credit below `REISSUE_FEE_FULL_CENTS` 500); fixtures deliberately use a two-line cycle (total 2644 → gross 634, basis 2010, fee 250, net 384) so the reduced fee tier is exercised.
- `Patient.anchor_fill_day` is schema-constrained `1..31` while the business ceiling 28 is enforced at priority 42, which is what keeps `ERR_INVALID_ANCHOR_DAY` distinguishable from `ERR_INVALID_REQUEST`.

## Step 3: Copy shared files — 2026-09-02T05:32:30.000Z

Copied `INSTRUCTION.md` to `tasks/task_2350_multi_dose_adherence_packaging_mail/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T05:35:00.000Z

PRD generated at `workspace/PRD.md` — 571 lines.

**Structure**

- `# Multi-Dose Adherence Mail Pharmacy API — Product Requirements Document`
- **§1 Introduction** — the mail-order adherence-packaging business, the six actors, determinism and the logical clock.
- **§2 Global Specifications** — 12 subsections: 2.1 Actors, Authentication and RBAC (`X-User-ID`, `X-User-Role`, per-role exclusive/shared/forbidden powers, the full patient-scoping walk shipment→cycle→patient, prescription→patient, line→cycle, pouch→roll→cycle, and the existence-precedes-scoping rule); 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`); 2.3 Pagination, Ordering and List Filters (`limit` 10/1–100, `offset` 0, `total_count`, `has_more`, default `created_at` ASC with `id` tie-break, the two ordering exceptions, and the complete per-collection filter inventory); 2.4 Logical Clock; 2.5 Identity, Timestamps and Versioning; 2.6 Money, Percentages and Rounding (half-up cents vs `floor` percentages, inclusive/exclusive threshold discipline); 2.7 Interval and Date Semantics (the three coexisting conventions); 2.8 The Two-Dimensional Fill-Cycle State Model; 2.9 Stale-Version Protection (both OCC rules); 2.10 Segregation of Duties at the Packing Bench; 2.11 Validation Ordering and Error Precedence (all 45 priorities as a table); 2.12 The Credit Ledger.
- **§3 Business Logic & Workflows** — 9 subsections: plans/enrolment/regimen sync; opening a cycle and staging lines; payer adjudication (edits, holds, routing, provisional copay); prescriber refill-authorization chase; travel early-supply exceptions; the pouch bench (roll generation, packing, imaging, scanner pass, verify, rework); split shipment, dispatch, delivery and cold-chain excursions; pickup, adherence-gap detection and auto-ship posture; mid-cycle regimen change and partial reissue.
- **§4 Endpoint Definitions** — 53-row, 4-column table (Method, Path, Description, Authorized Role(s)).
- **§5 Error Code Catalogue** — 56-row, 2-column table.

**Coverage notes** — Machine-verified against the scaffold: all 53 endpoints present with method, path and exact role lists matching; all 56 error IDs present with matching HTTP statuses; §2.2 byte-identical to the source. Resolved scaffold conflicts, documented in prose: `X-User-Role` (SKILL.md) over the scaffold's `X-Role`; `line_start_date` (not `cycle_start_date`) stamped as `last_dispensed_date`, with a note that they coincide absent bridge days; `contents` rendered with the entity's `{prescription_id, quantity}` shape rather than the calculation's drug-name list; the DRAFT→LINES_ADJUDICATED precondition's mis-cited priority stated as a rule without a wrong number; `packaging` omission stated as `STANDARD`; the synchronize precondition stated as a precondition since the scaffold declares no error ID for it. The scaffold's own section comment ("52 endpoints") is off by one — there are 53.

**Hard Contract reports** (message-only; not written into PRD.md or any sibling file):

- **Contract 1 — Field-Name Coverage: PASS.** 171/171 identifiers appear verbatim in backticks — every field across the 12 entities, every request-body field, every query and path parameter, the computed adherence-summary fields (`rolling_28_day_score_pct`, `cycle_scoped_score_pct`, `taken_count`, `missed_count`, `expected_pouch_count`), the OCC fields, `current_utc`, and the common/pagination fields. Missing: 0.
- **Contract 2 — Rule Coverage: PASS.** All 45 validation priorities with error ID, HTTP status and `applies_to` scope in §2.11; both OCC rules with exact error IDs and 412 in §2.9; all 8 calculations in prose (both alignment variants, refill-too-soon floor with inclusive threshold, four-ceiling allowance, both copay rounding variants with the delta/true-up rule, roll geometry with inclusive segment end, the four ordered reissue-credit steps with fee tiers 5000/2000/250/500, additive freight, both adherence variants with the score-first pause gate); all 8 state machines' transitions and every cross-entity cascade expressed; all field defaults stated; sibling-branch symmetry preserved (verify pass/fail, deliver ordinary/`EXCEPTION_RETURNED`, decide pharmacist/payer/deny, respond approve/deny, chase from `SENT`/from `NO_RESPONSE`, auto-ship PAUSE/RESUME/CANCEL, the two vacation-approval branches differing only in `waives_refill_too_soon`).
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, equal a bare HTTP method, or combine method+path; all filter parameter names live in §2.3 and §3 refers to operations only by state-transition framing, role + gerund, or capability description.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T06:30:00.000Z

Suite generation is complete and both final passes are clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2350_multi_dose_adherence_packaging_mail/`)

**`test_helpers/` — 9 files, 2,983 lines:** `__init__.py` (flat barrel), `api_client.py` (`ApiClient` + one method per PRD endpoint, `api_client` singleton), `api_errors.py` (all 56 `ApiErrorId` attributes + `HTTP_STATUS_CODES` registered via `set_error_http_status_map`), `constants.py`, `factories.py`, `fixtures.py` (`Scenario`, 27 single-call wrappers, 20 `setup_*` composite builders), `assertions.py`, `test_users.py`, `types.py`.

**`test_suite/` — `conftest.py` + 19 test files, 8,347 lines:** `test_01`–`test_10` (queue A) and `test_11`–`test_19` (queue B).

## Counts

- **187 test functions, 197 collected items** (parametrized families).
- **Queue A (Difficulty): 78 tests across 25/25 instances** — every instance has ≥2 tests; none uncovered.
- **Queue B (Corner): 109 tests across 72/72 non-stub instances** — none uncovered. All 31 `excluded_because:` stubs received nothing.

## Instances skipped

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. What was dropped is individual *assertions* inside otherwise-kept instances, where one asserted literal was not uniquely derivable from PRD prose (R4). Recurring cases:

- Exact wire spelling of domain timestamps (`staged_at`, `packed_at`, `decided_at`, `dispatched_at`, `applied_at`, `next_chase_due_at`, `last_sent_at`) — asserted as instant prefixes, because the PRD pins three fractional digits only for `created_at`/`updated_at`/`api_request_timestamp`.
- "field X is not accepted as an input" claims (`packable`, `id` on POST) — the PRD forbids supplying them but never fixes the observable outcome (400 vs. silently ignored).
- Geometry/copay literals imported into instances grounded on unrelated rules (e.g. `pouch_count == 28` inside RBAC and validation instances).

## Design-index conflicts worth forwarding to whoever owns the two yamls

1. `Corner/state_machines/denied_authorization_cannot_be_chased` expects `insurance_status CLEARED` after a denial, but §3.4 requires at least one `ADJUDICATED` line to clear, and the instance's only line becomes `EXCLUDED_HELD` → PRD predicts `EDITS_PENDING`.
2. `Corner/validations/chase_at_exactly_seventy_two_hours_is_allowed` expects post-chase `status SENT` with moved send timestamps; §3.4 sets `NO_RESPONSE` and raises `chase_round` instead.
3. `Corner/rbac/every_role_is_refused_another_roles_exclusive_operation` expects `packaging_status ROLL_GENERATED`, but its own setup packs the roll (§3.6 → `PACKED`).
4. `Difficulty/compensating_invariant/cold_chain_reversal...` asserts `delivered_at` is *not* stamped; §3.7 says it is set in both branches.
5. Status-code drift: the yamls give 422 for `ERR_PATIENT_NOT_SYNCHRONIZED`, `ERR_CHASE_TOO_EARLY`, `ERR_ESCALATION_PREMATURE`; §5 catalogues all three as 409. Tests assert through `validate_error`, so the PRD catalogue wins.
6. Enum spelling: yaml `APPROVED_PHARMACIST` vs. PRD `PHARMACIST_APPROVED`; PRD spelling asserted.

## Verification run

`python3 /tmp/task_2350_audit.py` reports **`problems: none`** — exactly one terminal `Design:` line per test, every tag resolving to a real non-stub instance (no stub tags, no dual tags, no unknown names), every docstring carrying a ≥12-word citation that survives a literal grep of `workspace/PRD.md`, no banned vocabulary (`scaffold`, `design yaml`, `§1.x`, `Table 1`), and `py_compile` clean on all 19 files. Additionally: `pyflakes test_suite/*.py` silent, every name imported from `test_helpers` verified to exist by reflection, no direct `prd_bench_local_runner` imports in the suite, no `skip`/`xfail`/mocks/`monkeypatch`/placeholders, and `pytest --collect-only` collects all 197 items.

## Step 6: Generate implementation — 2026-09-02T06:30:00.000Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2350_multi_dose_adherence_packaging_mail/workspace/implementation/`:

- Launcher/deps: `start.sh` (guarded pip install, `exec python3 app.py`, honours `$PORT`, default 10000), `requirements.txt`
- Core: `app.py` (9 blueprints under `/pharmacy`, error envelope handlers, `/health`), `db.py` (12 in-memory dicts, all empty at boot; monotonic UUIDv7 id generator), `store.py` (row create/touch/commit, one version bump per row per request, ordering, date helpers), `clock.py` (settable logical clock, canonical 3-digit-millis ISO), `errors.py` (56 error IDs), `response.py`, `middleware.py` (identity/RBAC), `validators.py`, `enums.py`, `calc.py` (Decimal/ROUND_HALF_UP money, floor percentages, alignment), `engine.py` (copay recompute, credit memos, dispense stamp/reversal, adherence)
- Routes: `routes/reads.py` (25 GETs), `setup.py`, `patients.py`, `cycles.py`, `rolls.py`, `shipments.py`, `auths.py`, `vacations.py`, `prescriptions.py`

## Endpoint count
53 routes under `/pharmacy`: 25 GET + 28 POST (the 28 includes `POST /_clock/set_current_utc`). 56 distinct error IDs; 45 validation rules in strict ascending priority.

## Notable design decisions
- Storage is in-memory only and empty on boot (verified: `tables non-empty at boot: []`), so `--isolation per-test-server` gets a clean state each launch.
- Version bumps are collected via `flask.g._touched_rows` + `store.commit()`, guaranteeing exactly one bump per mutated row per request even through cascades.
- Validation is a single ordered gate chain per endpoint; the first match returns and nothing is written. Adjudication computes every line figure first, then runs the atomic `ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE` sweep, so an over-allowance line leaves the cycle at DRAFT / NOT_ADJUDICATED / version 1 with all lines PLANNED.
- Money: per-line provisional copays are rounded then summed; the final copay sums raw values and rounds once at dispatch, emitting a `ROUNDING_TRUEUP` memo for a positive delta.
- IDs are UUIDv7-style and monotonic, so `(created_at, id)` ordering equals insertion order — list reads now sort on `created_at, id` literally as PRD 2.3 states (the internal `_seq` tie-break was removed this session).
- OCC via required `expected_*_version` at priority 7 (412); segregation of duties keyed on `X-User-ID` vs `packed_by_user_id`; `X-User-Role` preferred with tolerant `X-Role` fallback.
- Interval conventions: half-open cycle windows, closed-inclusive roll segments (`segment_end_date = max(line_end) - 1 day`), exclusive `line_end_date`, 48h-buffered cold-chain instants.

## Verification
Both external smoke suites pass end to end ("all expectations met"): every SCAFFOLD worked example reproduces (copays 762/1658/986/986 → provisional 4392, final 4390, delta 2; refill_pct_used 75/86/93/100/36; allowance 28 and 35 with a 7-day vacation exception; BRIDGE 28 vs TRIM 21/trim 7; 112-pouch roll), plus cold-chain reversal, chase/escalate loop, reissue arithmetic (31080 = 29000 + 2080 credit + 0 fee), roll truncation, pickup-grace sweep, and adherence pause. `start.sh` boots cleanly from a fresh process and serves correct envelopes; `python3 -m compileall` clean.

Note: the host has ~77 unrelated `python3 app.py` servers from other tasks, and port 10731 was already taken, so I ran on ports 10732/10836/10837 and killed only my own PIDs by port.

## Step 7: Run tests and iterate — 2026-09-02T11:45:00.000Z

The exit condition is met on the first sweep — no fixes were needed.

## Summary

**Iterations run:** 1 (single 8-round parallel stability sweep, all 8 rounds run to completion under `setsid nohup`, `--isolation per-test-server`).

**Sweep result:** all 8 rounds clean.

| Round | total | passed | failed | errors | skipped | duration |
|---|---|---|---|---|---|---|
| 1–8 | 197 | 197 | 0 | 0 | 0 | ~712 s each (wall ~19 min for the whole concurrent sweep) |

197 collected items from 187 test functions (parametrized families account for the difference). No round showed a `Terminated` in the server logs, so no reaping artifact and no load-induced connection failures — the sweep was genuinely green, not lucky.

**Tests deleted:** none. No test failed, so no STEP 1 coverage/unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Notes for the caller:**
- Artifacts are at `/home/ubuntu/github/CodingPRD/tasks/task_2350_multi_dose_adherence_packaging_mail/` — suite in `test_suite/` (19 files, `test_01`–`test_19`), helpers in `test_helpers/` (9 files), implementation in `workspace/PRD.md` + `workspace/implementation/`.
- Per-round result files were left in place at `workspace/implementation/results.1.json` … `results.8.json`, with the combined pytest output at `workspace/sweep.log`, in case you want the raw evidence.
- The implementation satisfies the benchmark's storage constraint as written in `worklog.md` and confirmed by the clean per-test-server sweep: state is in-memory dicts only (`workspace/implementation/db.py`), empty at boot, so each `start.sh` re-invocation wipes all state.

### Orchestrator verification (independent of the subagent's report)

All eight `results.$i.json` re-read directly by the orchestrator: every round reports `total 197 / passed 197 / failed 0 / errors 0 / skipped 0`. Newest mtime across `test_suite/*.py` and `test_helpers/*.py` is 07:30 UTC, predating this resume session entirely, confirming the subagent edited nothing — the 0-fix claim is corroborated by the filesystem, not just self-reported.

### Step 8 skip decision

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. The skill's Step 8 skip condition therefore applies verbatim: `PRD.md` already determined every behavior the implementation exhibits at every site the test suite exercised, so there is no `<step_7_diff>` to hand off and no PRD-silence site to target. **Step 8 is SKIPPED; no `PRD_FINALIZED.md` is produced.** Step 9 consumes `workspace/PRD.md` directly as its source, per its documented input rule ("Start from `workspace/PRD_FINALIZED.md` if Step 8 produced it; otherwise from `workspace/PRD.md`").

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T11:46:00.000Z

Skipped per the skill's documented skip condition. Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes, so there was no `<step_7_diff>` to hand off and no Step-7-revealed PRD-silence site to patch. No `PRD_FINALIZED.md` was produced; Step 9 took `workspace/PRD.md` as its source.

## Step 9: Complete PRD — 2026-09-02T12:05:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Summary

**Files**

| | lines | chars |
|---|---|---|
| `workspace/PRD.md` (source, untouched) | 570 | 108,057 |
| `workspace/PRD_COMPLETED.md` | 572 | 128,530 |

Char delta **+20,473**; line delta **+2** (two new bullets inside the existing §2.2 bullet lists). Section headings and Markdown table row counts are byte-identical to the source — no section was added, and every other change is an in-paragraph insert or revision.

**Counts:** 66 changes — **57 ambiguity-pins**, **9 mismatch-revisions**.

**Changes**

- §2.1 — insert — ambiguity — `X-Role` read as the role when `X-User-Role` is absent/empty — `middleware.py:16`
- §2.1 — insert — ambiguity — full ownership-edge set; list reads filter rather than fail — `middleware.py:75`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 uppercase alphanumerics — `response.py:13`
- §2.2 — **revise — mismatch** — `api_request_timestamp` comes from the wall clock, not the logical clock — `response.py:20`
- §2.2 — insert — ambiguity — dose-event batch is the sole `array` write response — `patients.py:168`
- §2.2 — insert — ambiguity — the eleven endpoints returning 201; all others 200 — `setup.py:56`
- §2.2 — insert — ambiguity — 404/405/400/500 all carry `ERR_INVALID_REQUEST`; trailing slashes tolerated; `/health` — `app.py:53`
- §2.3 — insert — ambiguity — cycle event stream tie-breaks on `created_at` then `id` — `reads.py:171`
- §2.4 — insert — ambiguity — instants accepted in any ISO form, normalized to 3-digit `Z` — `validators.py:102`
- §2.5 — insert — ambiguity — one `version` bump per row per request; no-op recomputes don't touch — `store.py:34`
- §2.11 p3 — insert — ambiguity — which date pair is compared; empty body = `{}`; `null` = absent; bool ≠ int — `validators.py:18`
- §2.11 p6 — insert — ambiguity — full scope-edge list; dose-event batch scope-checked twice — `middleware.py:75`
- §2.11 p9 — insert — ambiguity — sync's posture gate admits `PAUSED_PATIENT` — `patients.py:40`
- §2.11 p12 — insert — ambiguity — packing an empty roll is `ERR_INVALID_ROLL_STATE` — `rolls.py:28`
- §2.11 p26 — **revise — mismatch** — only the most recently created roll is consulted; no roll = same error — `shipments.py:41`
- §2.11 p37 — insert — ambiguity — day-supply check spans only this pass's lines — `cycles.py:184`
- §2.11 p40 — **revise — mismatch** — `approved_refills` below 1 or above 12 also 422 — `auths.py:128`
- §2.12 — insert — ambiguity — memos consumed whole; `credit_applied_cents` may exceed the total — `engine.py:163`
- §3.1 — insert ×4 — ambiguity — `bin_number`/`prescriber_npi` free text; patient strings and `date_of_birth` unconstrained; `written_date` vs `expiration_date` never compared — `setup.py:25,63,98,114`
- §3.1 — insert ×2 — ambiguity — sync gate order (posture before anchor ceiling, no-active before the sweep); projection writes only the two counters — `patients.py:40,75`
- §3.2 — insert — ambiguity — `day_supply_days` and resolved `sync_mode` stored on the cycle — `cycles.py:66`
- §3.3 — insert ×8 — ambiguity — `force_pouch_prescription_ids` is an assertion; pass scope; omitted `vacation_exception_id` keeps the stamped one; `refill_pct_used` 100 on zero prior supply; held lines still store figures; already-`PENDING_AUTHORIZATION` untouched; `insurance_status` over all lines; `credit_applied_cents` accumulates — `cycles.py:145,160,184,192,207,222,230`, `calc.py:74`
- §3.4 — insert ×4 — ambiguity — escalation drops every `HELD_AUTH` line across all cycles; approval writes `ACTIVE` unconditionally; revived line's `hold_reason` nulled; affected cycles visited once — `auths.py:97,153,158,179`
- §3.4 — **revise — mismatch** — denial writes `DISCONTINUED` unconditionally — `auths.py:171`
- §3.5 — insert ×2 — ambiguity — start-after-end is a 400 before the patient lookup; `DENY` leaves the patient untouched — `vacations.py:28,110`
- §3.6 — insert ×9 — ambiguity — `VOID` never written; `roll_serial` = `ROLL-`+8 hex; pack/verify/rework/imaging response bodies, version-bump conditions, override schema (unknown index ignored, duplicates last-wins), rework leaves the cycle untouched — `enums.py:63`, `cycles.py:333`, `rolls.py:28,49,71,81,123,153,185`
- §3.7 — **revise — mismatch** — dispatch reads the latest roll; `tracking_number` = `TRK-`+12 hex — `shipments.py:41`
- §3.7 — insert ×3 — ambiguity — empty required-kind set does not finalise (close happens once); `DELIVERY_EXCEPTION` event fields; exception branch always bumps the cycle — `shipments.py:58,144,146`
- §3.8 — insert ×3 — ambiguity — pickup event fields and conditional patient bump; pause cascade skips already-excluded lines and never writes `hold_reason`, gate no-ops unless `ACTIVE`; review always bumps the patient — `shipments.py:167`, `engine.py:309`, `patients.py:177`
- §3.8 — **revise — mismatch** — `dose_slot`/`pouch_index` optional and default null; HTTP 201 array response — `patients.py:137`
- §3.8 — **revise — mismatch** — `PAUSE` from non-`ACTIVE` fails; `RESUME` tolerated from any posture; `CANCEL` always allowed — `patients.py:100`
- §3.9 — insert ×5 — ambiguity — successor inherits NPI/flags/dates/`refills_authorized` and starts a fresh dispense history, `change_reason` discarded; roll row untouched by all cascades and the reverted cycle cannot mint a new roll; `replacement_prescription_ids` may be empty, members 404 before the stale check, duplicates collapse; zero `days_supply_filled` credits 0; zero-cent memo still issued — `prescriptions.py:58,110`, `cycles.py:476,555`, `calc.py:131`
- §3.9 — **revise — mismatch** — `total_copay_cents` recomputed including the now-`REISSUED` lines — `cycles.py:552`
- §3.9 — **revise — mismatch** — every roll truncated; pouches left in place, counts and statuses unchanged — `cycles.py:547`
- §3.9 — insert — ambiguity — successor cycle field defaults, distinct lines in `created_at` order, original's `packaging_status`/`reissue_required` untouched — `cycles.py:557`

One correction worth flagging: an early draft claimed a regimen-change-reverted cycle could generate a replacement roll. It cannot — `generate_roll` demands `LINES_ADJUDICATED` (`cycles.py:279`) — so the prose was fixed to say the partial reissue is the only route forward.

### Orchestrator verification

`diff <(grep '^#' PRD.md) <(grep '^#' PRD_COMPLETED.md)` is empty — heading structure is byte-identical, confirming no section was added or renamed. `PRD_COMPLETED.md` is 572 lines / 128,530 chars and terminates on the complete §5 error-code table (last row `ERR_NOTHING_TO_REISSUE | 422`), so the file is not truncated.

### Pipeline status: COMPLETE

All nine steps accounted for: Steps 1–6 pre-existing and verified on disk this session; Step 7 re-run as mandated and green across all 8 rounds (197/197 each); Step 8 skipped under its documented condition; Step 9 produced `workspace/PRD_COMPLETED.md`.
