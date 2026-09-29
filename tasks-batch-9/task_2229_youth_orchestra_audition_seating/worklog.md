# Worklog — task_2229_youth_orchestra_audition_seating

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2229_youth_orchestra_audition_seating/` and `tasks/task_2229_youth_orchestra_audition_seating/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T10:41:00.000Z

(First launch terminated early due to an upstream API error; relaunched and completed.)

All three scaffold artifacts are complete and the lint is clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2229_youth_orchestra_audition_seating/`):
- `SCAFFOLD.yaml` — 3353 lines / 164 KB; top-level keys are §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`; 223 KB.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`; 8076 lines / 494 KB.

**SCAFFOLD.yaml counts (above Expert on every axis):** 13 entities, 10 state machines (Member, TuitionAccount and EventParticipation each carry parallel independent dimensions), 15 calculations, 49 ordered validations across 9 priority bands (1–7, 20–25, 30–31, 40–47, 50–57, 60–66, 70–72, 80–84, 90–92), 60 endpoints, 65 error codes, 5 roles, 3 OCC `concurrency_rules`. Profile: `primary_archetype: quota_allocation`, `secondary_archetype: multi_party_negotiation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`, `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

**Difficulty design (§1.8):** 9 rule blocks, **25 instances** — dual-variant divergence (provisional/final audition composite, preliminary/final tuition), triple-min aid grant with a 5000 floor branch, pinned rounding and cap-evaluation order, revision-round recompute, three-dimension parallel advancement, offer/waitlist fork, the four-hop acceptance cascade, excuse-denial probation and aid-rescind delinquency cascades, four priority-band collisions, four exact boundaries (attendance index 80.00 vs 79.17, aid floor 5000 vs 4999, 15- vs 14-minute room buffer), buffered-strict vs plain half-open calendar overlaps, and three conservation identities (aid pool, chair multiset, seat ledger).

**Corner design (§1.9):** all nine guide sections, **70 instances** (61 live recipes + 9 `excluded_because` stubs, every cited difficulty instance verified to exist by name): entities 11, state_machines 14, calculations 12, validations 8, endpoints 6, errors 11 bundles covering the previously-unexercised ~39 error ids, rbac 4 (exclusive / shared / cross-role 403 sweep of 14 exclusive writes / segregation-of-duties keyed on `X-User-ID` not role), cross_cutting_complexity_layers 3 (one live `optimistic_concurrency` instance walking all three concurrency rules — stale `expected_ensemble_version` on `POST /placements` and on `rotate-chairs`, stale `expected_season_version` on `aid-award-run`, each 412 then a successful retry; stubs for the cascade and dual-variant layers), consistency_model 1 (`immediate`).

**Lint:** `scaffold_lint.py` reports `VERDICT: clean lint` over 2379 scanned calls (60 endpoints, 13 entities, 25 §1.8 instances, 61 §1.9 instances) — all calls conform to §1.5 and every §1.1 FK is reverse-reachable. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-01T10:41:30.000Z

Copied `INSTRUCTION.md` → `tasks/task_2229_youth_orchestra_audition_seating/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T10:58:00.000Z

PRD written and all three Hard Contracts verified mechanically.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2229_youth_orchestra_audition_seating/workspace/PRD.md` — 430 lines, ~12,900 words. Document ends at §5; no audit footer written into the file or any sibling.

**Sections covered**
- §1 Introduction (2 paragraphs + logical-clock framing)
- §2, eleven subsections: 2.1 Roles/RBAC (opaque vs. entity-backed identity, the 8 ownership-guarded operations), 2.2 API Response Structure (byte-verbatim paste), 2.3 Pagination & List Ordering (all 13 filter sets), 2.4 Record Identity/Timestamps/Version (incl. the `PanelScore` `id`+`created_at`-only exception), 2.5 The Logical Season Clock, 2.6 Cascade Propagation, 2.7 Money & Rounding Discipline, 2.8 OCC against stale reads, 2.9 Path Resolution & Reverse Discovery, 2.10 Rejection Precedence (all bands + 5 called-out cross-band inversions), 2.11 The Conserved Aid Pool
- §3, nine subsections: season/ensemble/section setup, members' two standing dimensions + adjudicators, audition calendar (buffered room/panel overlap), request→adjudication (dual composite variants), placement/waitlist/seating, chairs & rotation, tuition/aid/loans (waterfall + income-band cap), attendance & performance eligibility, programming/tours/graduation
- §4 all 60 endpoints (4-column table), §5 all 65 error codes (2-column table)

**Contract 1 — Field-Name Coverage: PASS.** 153/153 `entities[].fields[].name` present verbatim in backticks; 96/96 distinct endpoint `input`/`query_params` identifiers present; 13/13 path params (`seasonId`…`participationId`) named in §2.9; 5/5 non-entity response fields (`current_utc`, `expired_count`, `promoted_count`, `approved_count`, `denied_count`) present. Verified by script against SCAFFOLD.yaml (initial run gave false negatives until fenced code blocks were stripped from the backtick scan).

**Contract 2 — Rule Coverage: PASS.** 73/73 state-machine transitions described (22 stated in prose form rather than literal `X → Y` arrows — e.g. ensemble `FORMING`/`SEATED` to `CLOSED`, account `CURRENT`/`DELINQUENT` to `PAID_IN_FULL`, all four `NOT_RECORDED` attendance branches — each manually confirmed present with both endpoints named). All 3 `concurrency_rules[]` in §2.8 with the correct non-optional OCC field, parent entity, error and stale-read rationale. All 49 validation priorities reproduced in §2.10 band order, with priority 62's six duplicate codes sharing one rank. All 65 error ids appear in §1–§4 prose, not merely in the §5 table. All 15 calculations reproduced with every constant; the only numeric literals not appearing digit-for-digit are `0.015`, `0.25`, `0.3`, `0.4`, `15`, each rendered as spelled-out percentages/minutes ("one and a half percent", "twenty-five percent", "thirty percent", "forty percent", "fifteen-minute"). Worked fixtures kept: 81.35/82.10 composites, 123223→109053 (vs. the wrong 109052), BAND_C cap 27263, waterfall 30000/30000/30000/denied/10000, attendance 80.00 vs. 79.17, 62.50 vs. 62.49.

**Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 (and in §1–§2) begin with `/`, are a bare HTTP method, or combine method+path; no raw method words or `/path/{id}` fragments appear in §3 outside backticks either. All §3 operations are framed as state transitions, role + action verb, or capability descriptions. Paths and methods appear only in the §4 table.

**Zero-Silence Rule notes (three scaffold gaps closed by explicit decision, all stated in the PRD):**
1. Two audition-scheduling preconditions carry no `error_id` in the scaffold — the `standing_status` must-be-`CLEAR` gate and the "slot has not already begun" gate. Both are attributed to `ERR_INVALID_STATE_FOR_OPERATION` (409), the catalogue's only generic state-conflict code; no new error id was invented.
2. The waitlist-promotion capacity guard is phrased two ways in the scaffold (the state machine counts `OFFERED` placements on the section; the calculation uses the ensemble's `offered_count`). The PRD follows the calculation: section `filled_count` plus ensemble `offered_count` strictly below the section's `max_count`.
3. `instrument_class_loaned` is not an endpoint input anywhere, so §3.5 pins it as derived from the member's own `instrument_class` when `instrument_loan_requested` is true, and null otherwise — which is what makes the `STRING`/`WIND`/`PERCUSSION` loan-fee selection in §3.7 well-defined.

The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T11:29:00.000Z

Suite is complete and audited. Final report:

## Files written

**Stage 1 — `test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_2229_youth_orchestra_audition_seating/`)
- `types.py` — 32 status enums, `UserRole`, 13 entity TypedDicts. `PanelScore` deliberately omits `updated_at`/`version` (PRD §2.4's single exception).
- `api_errors.py` — all 64 error ids + HTTP status map, registered via `set_error_http_status_map`.
- `api_client.py` — one method per PRD §4 endpoint (~70).
- `constants.py` — every literal the PRD pins (rubric weights, tier bands, tier multipliers, loan fees, aid caps/points/floor, attendance weights, 15-minute room buffer, 72h/48h windows, fee cap) plus deterministic fixture instants.
- `factories.py` — per-endpoint payload builders with `**overrides` (a `None` override deletes the key, so "missing required field" cases are one-liners).
- `test_users.py` — opaque operator headers (two distinct ids per role, for the two segregation-of-duties rules) plus `guardian_headers(member_id)` / `panelist_headers(panelist_id)` for the entity-backed roles.
- `assertions.py` — common-field/immutable-sheet shape, rounding, aid-pool conservation, balance identity, contiguous chair numbers, pagination meta, instant arithmetic.
- `fixtures.py` — composite builders driving the full workflow from an empty DB: `open_season_with_ensemble` → `scored_audition` → `adjudicated_audition` → `placement_offer` → `accepted_placement`, plus reads and filtered-list discovery for the two client-uncreatable entities.
- `__init__.py` barrel.

**Stage 2 — `test_suite/`** — `conftest.py` + 10 test files, **288 tests**.

## Test counts per queue

| Queue | Instances | Tests |
|---|---|---|
| A (Difficulty §1.8) | 25 non-stub | **111** |
| B (Corner §1.9) | 61 non-stub | **177** |

Queue A: calculations 20, state machines 52, precedence/boundaries 16, cross-entity/invariants 23.
Queue B: entities 26, state machines 24, calculations 27, validations+endpoints 30, errors 40, rbac/cross-cutting 30.

## Instances skipped

**None.** All 25 difficulty and all 61 non-stub corner instances passed the PRD-first two-condition filter and are covered. The 9 `excluded_because:` stubs were not translated.

A handful of individual *sub-assertions* inside otherwise-valid instances were dropped rather than weakened, because the PRD does not uniquely derive them — e.g. the initial null values of an audition's three derived scoring fields (§3.4 stamps only `status`, `revision_round`, `slot_id`, `blind_code`), a denied aid account's `aid_effective_cents` (the denial branch pins only `aid_awarded_cents` to 0), an exact `blind_code` format (the PRD gives an example, not a grammar), and one absolute season `version` total after a rejected write.

## Verification performed

- Coverage audit against both design yamls: 0 missing instances, 0 unknown tags, every difficulty instance ≥2 tests, every non-stub corner instance ≥1 test.
- 288 tests / 288 `Design:` lines — exactly one per test, always the docstring's last line.
- All 288 PRD quotes confirmed **character-for-character** present in `workspace/PRD.md`; exactly one quote per docstring; **zero** quotes sourced from the §4 endpoint table or §5 catalogue (all come from §2/§3 prose, so C2 holds).
- Zero `pytest.mark.skip`/`skipif`/`xfail`/`pytest.skip`.
- Zero generator vocabulary anywhere outside the `Design:` lines.
- `py_compile` clean on all 19 files; all 10 test modules import successfully; all `api.*`, `ApiErrorId.*`, and helper-module attribute references resolve (0 unresolved).
- `pytest --collect-only` collects exactly 288 tests with no collection errors.
- The implementation directory was never read; no sibling task directory was read; scratch slice files used for parallel translation were removed.

## Step 6: Generate implementation — 2026-09-01T11:52:00.000Z

Implementation complete and smoke-verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2229_youth_orchestra_audition_seating/workspace/implementation/`)

Infrastructure (written earlier in this task): `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validate.py`, `calc.py`, `services.py`.

New this session:
- `routes/tuition.py` — accounts list/read, `finalize-assessment`, `aid-request`, `aid-review`, `aid-rescind`, `payments`
- `routes/events.py` — events CRUD + `programming`, participations CRUD + `attendance`, `excuse-request`, `excuse-decision`, `eligibility-review`, `tour-requirements`
- `routes/__init__.py` — `BLUEPRINTS` tuple (8 blueprints: clock, seasons, ensembles, members, auditions, placements, tuition, events)
- `app.py` — factory, `ApiError` handler, 404/405/HTTPException/500 handlers, `PORT` (default 10000), `0.0.0.0`
- `requirements.txt`, `start.sh` (executable; guarded flask install then `exec python3 app.py`)
- One fix in `services.py`: the 4th hop of the probation cascade (soloist vacancy) is now a standalone sweep over all `PROGRAMMED` events instead of being nested inside the participation loop, so it fires even without a participation row on the soloist's event.

## Endpoint count
60 routes, verified programmatically to be an exact set-match against the PRD §4 table (no missing, no extra).

## Verification
Four scripted end-to-end walkthroughs (~200 assertions) all pass, exercising: full season ladder PLANNING→CLOSED, slot booking with the 15-min room/panelist buffer, scoring→quorum→provisional→revision round→re-book→re-score→adjudicate, placement OCC (412), capacity refusals, acceptance cascade (seat + chair ranking + quota FULL + ensemble SEATED + season IN_SEASON + PROSPECT→ENROLLED + preliminary assessment), decline/expiry sweep→waitlist promotion (72h TTL), chair rotation, vacate→SEATED→FORMING, aid request/review/award-run/SoD/rescind, payments (DELINQUENT→FINANCIAL_HOLD→graduation blocked), excuse flow with segregation of duties, attendance index (0.00 / 100.00 boundaries), tour readiness, AUTO_SELECT + MANUAL soloist selection with the already-booked exclusion, and CLOSED cascade → GRADUATED → ALUMNI. PRD worked examples reproduce exactly: assessed 109053 from 12322 + 1848, BAND_C cap 27263, `committed + available == budget` preserved across award/cap-surplus/rescind.

## Notable design decisions
- Storage is in-memory dicts only; empty on every boot (verified all 13 collections return `total_count: 0` from a fresh process). No file, no seeding.
- Money and scores use `Decimal` with `ROUND_HALF_UP` throughout; components rounded before subtraction per the pinned rounding order.
- `version`/`updated_at` bump at most once per row per HTTP request (`flask.g` identity set), so multi-hop cascades increment exactly once.
- All counters derived live except `aid_committed_cents`, which is stored so the FINAL-assessment cap surplus can decrement it while `aid_awarded_cents` stays.
- `created_at`/`updated_at` use wall time (monotonic, spec only binds the logical clock to deadlines/windows); every deadline, expiry and window reads `clock_now()`, defaulting to `2026-08-01T00:00:00Z`.
- Rejection order follows §2.10 bands, with body FK resolution ahead of all state checks; `GET /seasons` sorts ascending by `created_at` per PRD §2.4 (the SCAFFOLD's "newest first" note was rejected as it is contradicted by the PRD's own endpoint description).
- `app.run(threaded=True, use_reloader=False)` so health-check polls cannot block behind an in-flight request.

## Step 7: Run tests and iterate — 2026-09-01T12:22:00.000Z

All 8 parallel rounds pass at 288/288.

## Summary

**Iterations run:** 2 (sweep 1 → one fix → sweep 2 clean).

**Sweep 1:** 287/288 in all 8 rounds — a single, fully deterministic failure (no flakiness anywhere in the suite; the same test failed in every round with the identical error, and no other test failed in any round).

**Tests deleted:** none. No test failed the STEP 1 coverage / unique-derivability checks outright.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2229_youth_orchestra_audition_seating/test_suite/test_corner_validations_and_endpoints.py`, `test_string_instrument_loan_is_priced_at_forty_five_hundred_cents` (line 1097): the assertion read `instrument_class_loaned` off the **tuition account** (`KeyError: 'instrument_class_loaned'`); retargeted to the **placement** row, which is where PRD hosts it. This is a STEP 2 assertion mis-translation fix, not a weakening — the other three account-side assertions (`instrument_loan_fee_cents == 4500`, `assessed_cents == 123223`, `balance_cents == 127723`) were all kept intact.

  Justification: PRD §3.5 sets the field during placement acceptance ("when it is true, `instrument_class_loaned` is set to the musician's own `instrument_class`, and when it is false or absent, `instrument_class_loaned` stays null") and PRD §4 declares `GET /placements/{placementId}` as "Read one placement with its waitlist rank and **loan flags**", while the account read is "its components, aid trail and balance". §3.7 names `instrument_class_loaned` only as the *selector* inside the loan-fee formula, never as an account attribute — a computed-field-silence pattern on the account side. The suite's own type model agreed: `test_helpers/types.py:417` declares `instrument_class_loaned` on `Placement` and not on `TuitionAccount`, and three sibling tests in `test_corner_calculations.py` (lines 590, 603, 618) already assert it via `ctx["placement"]`. The single account-side read was the outlier.

**Fixes applied to `implementation/`:** none. The implementation's placement-hosted loan flags (`workspace/implementation/services.py:408-409` serializer, set at `routes/placements.py:169-170`) trace correctly to PRD §3.5/§4; no PRD-required check was removed or relaxed, and storage remains in-memory dicts only.

(Orchestrator verification: all eight `workspace/implementation/results.{1..8}.json` read `288 / 288`.)

## Step 8: Finalize PRD — 2026-09-01T12:25:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 429 lines / 94,545 bytes
- `PRD_FINALIZED.md`: 429 lines / 95,044 bytes
- Delta: **0 lines (0.00%)**, +499 bytes (+0.53%) — the change is inline inside §3.5's acceptance paragraph (source line 212).

## Change
- **§3.5 (placement acceptance, loan flags)** — *insert* — pinned that `instrument_loan_requested` and `instrument_class_loaned` are fields of the **placement** row and of no other record: born false/null on both the `OFFER` and `WAITLIST` branches, set only at acceptance, and read back through the placement; the tuition account hosts neither field, only the resulting `instrument_loan_fee_cents` — `implementation/routes/placements.py:94-95`, `implementation/routes/placements.py:169-170`, `implementation/services.py:408-409`, `implementation/services.py:439`.

## Pre-edit search log (mandatory per NO-NEW-MISMATCH)
**Edit 1**
- **(a) Subject:** which entity hosts `instrument_loan_requested` / `instrument_class_loaned`, and how the loan-fee consumer reaches them.
- **(b) Impl paths enumerated** (grepped `instrument_class_loaned|instrument_loan_requested|instrument_loan_fee_cents` across all of `implementation/`, then read each site):
  - `routes/placements.py:94-95` — placement row is created with `instrument_loan_requested: False`, `instrument_class_loaned: None`; the block is shared by both the `OFFER` and the `WAITLIST` branch (branch-specific fields are set afterwards), so "every placement is born …" holds.
  - `routes/placements.py:169-170` — acceptance is the only writer; sets the flag from the body and the class from `member["instrument_class"]` when true, `None` otherwise. No other code path (decline, expiry sweep, vacate/`RELEASED`, waitlist promotion, member-status cascades) writes or resets either field — grep returned no other assignments, so I avoided any claim about clearing them on terminal transitions.
  - `services.py:408-409` — `placement_json` exposes both fields, which is the read channel used by `GET /placements`, `GET /placements/{placementId}` and the 201 from `POST /placements`; matches PRD §4's "loan flags" on the placement read.
  - `services.py:439` / `services.py:595` — `account_json` and the account-creation row (`ensure_tuition_account`) contain `instrument_loan_fee_cents` but no `instrument_class_loaned` / `instrument_loan_requested` key at all — hence the explicit negative clause about the account.
  - `services.py:673-674` (`preliminary_assessment`) — computes the account's `instrument_loan_fee_cents` by reading `placement["instrument_class_loaned"]` / `placement["instrument_loan_requested"]`; consistent with "read back through the placement".
  - `routes/tuition.py:134-135` (`aid-review`) — the +6 need-score term also reads `placement["instrument_loan_requested"]` via `_accepted_placement`, a second consumer on the placement side (PRD §3.7 already says "on the accepted placement").
  - `routes/tuition.py:48-82` (`finalize-assessment`) — verified it does **not** recompute `instrument_loan_fee_cents`; the preliminary figure carries forward. Checked so the new sentence would not imply a FINAL-variant re-pricing.
  - `calc.py:158-161` (`loan_fee`) — falsy/None class yields 0, matching "when no loan was requested it is 0" in §3.7.
- **(c) Wording adjustment made:** two. (1) Added the explicit "`OFFER` or `WAITLIST`" scope after confirming the initialization block precedes the branch fork, so the birth-value claim would not be read as offer-only. (2) Phrased the account clause as "carries no … field of its own; what it holds is the resulting `instrument_loan_fee_cents`" rather than "the loan is not recorded on the account", so §3.7's account-side fee field and its serialization at `services.py:439` stay true, and no implication of a FINAL-variant re-pricing is introduced. Left §3.7's existing "selected by `instrument_class_loaned`" prose verbatim — with §3.5 now pinning the host row it resolves uniquely without a second edit.

No other `<step_7_diff>` item required a PRD change: no implementation or `test_helpers/` fixes were applied, and no tests were deleted.

## Step 9: Complete PRD — 2026-09-01T12:40:00.000Z

`PRD_COMPLETED.md` is written and verified.

## Counts

- Source `workspace/PRD_FINALIZED.md`: 429 lines / 95,044 chars → `workspace/PRD_COMPLETED.md`: 429 lines / 103,481 chars (**+8,437 chars**, line count unchanged).
- 47 changed lines (94 diff lines), 49 discrete in-paragraph edits. No new sections, no new paragraphs, no line insertions.
- **43 ambiguity-pins**, **6 mismatch-revisions**.

## Changes

- §2.1 — insert — ambiguity — an absent **or empty** `X-User-ID`/`X-User-Role` is `ERR_MISSING_AUTH_HEADERS` — auth.py:33
- §2.3 — insert — ambiguity — `created_at` ties break by server mint sequence, never by `id` — store.py:101
- §2.3 — insert — ambiguity — filters compare the field's string form (booleans as `true`/`false`, absent as empty string), out-of-domain values select nothing, slot `status` filters on the derived value, undeclared query params are ignored — services.py:503, routes/auditions.py:99
- §2.4 — insert — ambiguity — a row touched twice in one request advances `version` by exactly one; newly created rows return at version 1 — services.py:23
- §2.7 — insert — ambiguity — two-decimal figures travel as JSON numbers, so a trailing zero is dropped (82.10 → `82.1`) while comparisons use the two-decimal value — services.py:256
- §2.9 — insert — ambiguity — body FKs resolve in the order the fields are introduced for that operation in §3 — routes/auditions.py:129, routes/placements.py:33
- §2.10 — insert — ambiguity — datetimes with an explicit numeric offset parse and normalize to UTC; undeclared fields ignored; explicit null reads as absent; no-input operations accept an empty body — validate.py:22, validate.py:60, validate.py:74
- §3.1 — revise — ambiguity — `year_label` is 1–40 chars; audition-window bounds are never compared to each other at creation — routes/seasons.py:30
- §3.1 — insert — ambiguity — a `to_status` outside the five phase names is `ERR_INVALID_REQUEST`, not a transition error — routes/seasons.py:74
- §3.1 — revise — ambiguity — ensemble `name` is 1–200 chars — routes/ensembles.py:25
- §3.1 — revise — ambiguity — an ensemble owning no section quota never reaches `SEATED` — services.py:534
- §3.2 — revise — ambiguity — `legal_name` 1–200 chars; `graduation_year` has no upper bound — routes/members.py:38
- §3.2 — insert — ambiguity — `to_status` is validated against the union of both dimensions, so a cross-dimension value is refused as `ERR_INVALID_MEMBER_TRANSITION` — routes/members.py:90
- §3.2 — revise — ambiguity — panelist `display_name` 1–200 chars — routes/members.py:148
- §3.2 — revise — ambiguity — `conflict_member_ids` entries are opaque strings, never resolved against members — routes/members.py:152
- §3.3 — revise — ambiguity — `required_excerpt_codes` carries no cardinality or distinctness bound — routes/auditions.py:36
- §3.3 — insert — ambiguity — room and panelist buffered-overlap checks sweep every slot in the system, any season — routes/auditions.py:56, routes/auditions.py:67
- §3.4 — revise — ambiguity — `blind_code` = full instrument name + hyphen + 3-digit zero-padded per-instrument sequence counted across all seasons — services.py:888
- §3.4 — insert — ambiguity — a score sheet against a non-`SCHEDULED` audition is `ERR_INVALID_STATE_FOR_OPERATION` — routes/auditions.py:252
- §3.4 — insert — ambiguity — wrong season phase or lost quorum at adjudication is `ERR_INVALID_STATE_FOR_OPERATION` — routes/auditions.py:303
- §3.4 — insert — ambiguity — a revision request outside `AUDITIONS_OPEN` is `ERR_INVALID_STATE_FOR_OPERATION` — routes/auditions.py:331
- §3.5 — revise — ambiguity — a missing or non-future `offer_expires_at` is `ERR_INVALID_REQUEST` evaluated before FK resolution; the `WAITLIST` branch stores null — routes/placements.py:27
- §3.5 — revise — **mismatch** — an existing account for the member/season pair is reused as it stands (tier snapshot included); `ERR_DUPLICATE_TUITION_ACCOUNT` is never raised on the offer/promotion path — services.py:579
- §3.5 — insert — ambiguity — acceptance refusals map to `ERR_INVALID_STATE_FOR_OPERATION` (not `OFFERED`, lapsed, financial hold, delinquent), `ERR_NO_SECTION_FOR_INSTRUMENT`, and `ERR_SECTION_FULL_AT_ACCEPTANCE` for the `max_total_size` breach — routes/placements.py:138
- §3.5 — insert — ambiguity — sibling withdrawals clear `waitlist_rank`, densely renumber the section's waitlist, and run no promotion even from `OFFERED` — routes/placements.py:203, services.py:757
- §3.5 — revise — ambiguity — the expiry sweep promotes at most one row per freed ensemble-and-instrument pairing, has no phase gate, and answers with exactly `expired_count`/`promoted_count` — routes/seasons.py:159
- §3.6 — insert — ambiguity — the rotation answers with the section quota row (incremented `rotation_cycle_index`); successors are read via the chair list — routes/ensembles.py:164
- §3.7 — revise — ambiguity — finalize requires an `ACCEPTED` placement inside that account's season — routes/tuition.py:35
- §3.7 — insert — **mismatch** — any recomputation leaving balance ≤ 0 moves `CURRENT`/`DELINQUENT` → `PAID_IN_FULL` regardless of clock; `PENDING_ASSESSMENT` only ever leaves for `CURRENT` — services.py:623
- §3.7 — revise — **mismatch** — `amount_cents` below 1 is `ERR_PAYMENT_EXCEEDS_BALANCE`, not a schema error — routes/tuition.py:179
- §3.7 — insert — ambiguity — first-request phase failure is `ERR_INVALID_STATE_FOR_OPERATION`, checked before amount sizing — routes/tuition.py:99
- §3.7 — revise — **mismatch** — every admissible aid request overwrites `aid_requested_cents` and resets `aid_denial_reason`, not only a re-request after denial — routes/tuition.py:108
- §3.7 — insert — ambiguity — aid-review from any non-`REQUESTED` status is `ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE`, before the budget test — routes/tuition.py:124
- §3.7 — insert — ambiguity — the award run has no phase and no non-zero-budget precondition; an empty queue is lawful — routes/seasons.py:186
- §3.7 — insert — ambiguity — a denial leaves requested/effective/balance untouched and runs no billing recomputation — routes/seasons.py:212
- §3.7 — insert — ambiguity — rescission from any non-`APPROVED` status, or of a zero award, is `ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE` — routes/tuition.py:153
- §3.8 — revise — ambiguity — `venue_code` is 1–64 chars — routes/events.py:33
- §3.8 — revise — ambiguity — a missing `eligibility_window_start` on a performance kind is `ERR_INVALID_REQUEST` — routes/events.py:44
- §3.8 — insert — ambiguity — participation birth values: `attendance_index` null, `ineligibility_reason`/`excuse_reason_code` `NONE`, excuse and chaperone fields null, `chaperone_confirmed` false, both fundraising figures 0 (shortfall not seeded from cost share) — routes/events.py:180
- §3.8 — insert — ambiguity — the recording `X-User-ID` is kept internally as the SoD anchor and is not a readable field — routes/events.py:239
- §3.8 — revise — **mismatch** — the fourth cascade hop is an independent sweep over every `PROGRAMMED` event naming the musician as soloist, regardless of revoked rows, kind, ensemble or start time — services.py:796
- §3.8 — revise — ambiguity — excuse filing from any other `attendance_status` is `ERR_INVALID_STATE_FOR_OPERATION` (before the window test); `excuse_reason_code` is required; `excuse_documentation_ref` ≤ 200 chars and untouched when absent — routes/events.py:253
- §3.8 — insert — ambiguity — a row with no pending excuse is `ERR_INVALID_STATE_FOR_OPERATION`, checked before the SoD test — routes/events.py:280
- §3.8 — insert — ambiguity — the eligibility review has no state precondition and no body input; it may re-run from any value — routes/events.py:304
- §3.8 — revise — ambiguity — the dress condition uses the latest dress-flagged rehearsal by `start_at` and fails outright when the window holds none — services.py:874
- §3.9 — revise — ambiguity — `guest_artist_fee_cents` may not be negative (schema failure) — routes/events.py:96
- §3.9 — insert — ambiguity — under `NONE` and `AUTO_SELECT` a supplied `soloist_member_id` is still resolved (`ERR_MEMBER_NOT_FOUND`) and then ignored — routes/events.py:97
- §3.9 — revise — ambiguity — guest-artist fields are overwritten only when supplied (birth values null / 0) — routes/events.py:126
- §3.9 — revise — ambiguity — `fundraising_amount_cents` ≥ 0 and the two chaperone strings ≤ 200 chars, absent values left alone — routes/events.py:342
- §3.9 — insert — **mismatch** — `ERR_TOUR_REQUIREMENTS_UNMET` persists nothing (no fundraising credit, no version bump); a `READY` row may re-submit, accumulating credit and staying `READY` — routes/events.py:358
- §4 — insert — ambiguity — four operations answer with a non-resource payload: clock echo, sweep counters, award-run counters, and the rotation's section quota row — routes/clock.py:19, routes/seasons.py:172, routes/seasons.py:222, routes/ensembles.py:164
