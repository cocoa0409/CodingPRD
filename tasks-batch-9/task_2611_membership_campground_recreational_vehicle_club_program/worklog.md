# Worklog — task_2611_membership_campground_recreational_vehicle_club_program

## Step 1: Create task directory — 2026-09-03T19:32:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2611_membership_campground_recreational_vehicle_club_program` and its `workspace/` subdirectory. Index 2611 was pre-assigned by the invoker; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T21:44:00.000Z

All three scaffold artifacts for task 2611 are complete and lint-clean.

## Files written (absolute paths)

| File | Lines | Top-level key(s) |
|---|---|---|
| `.../SCAFFOLD.yaml` | 2,790 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no design keys |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,305 | `scaffold_difficulty_design` only (18 instances, 9 rule categories) |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 3,789 | `scaffold_corner_design` only (76 instances: 60 full recipes + 16 `excluded_because` stubs) |

§1.9 now walks all nine claim-guide sections: entities 11, state_machines 12, calculations 15, validations 10, endpoints 6, errors 8, rbac 4, cross_cutting_complexity_layers 8, consistency_model 2.

## Verdict block (verbatim)

```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  857

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(56 scanned = the 60 recipes minus 4 recipe-less stubs the lint skips; stubs carry no calls.)

## What this session added
- **errors** (8 instances): a consolidated 8-way 404 probe, double transfer decision, invoice payable/reversible directions, maintenance-window closed-interval vs. season-edge refusals, transient-pool exhaustion vs. member waitlisting, double-decided occupancy exception, three-generation transfer chain limit, and the GRACE-dues asymmetry.
- **rbac** (4): identity/role gates outranking existence, member-ownership denials, ParkManager park scoping, and segregation of duties on both decision endpoints.
- **complexity layers** (8): one OCC instance per `concurrency_rules` entry, a six-membership single-sweep test pinning all three dues thresholds from both sides (0/1/29/30/119/120 days past due), a threshold-reset instance, plus 4 stubs deferring the cascade and dual-variant rows to §1.8.
- **consistency model** (2): survey-triggered re-score with pre-computed literals (rating 0.00 → 4.60; projects 4200/2000 → 1686/803) and same-instant waitlist promotion on cancellation.

**Error catalogue coverage is now total: all 48 declared `error_id`s are asserted somewhere in §1.8/§1.9** (verified by a script that ignores `grounds:` lines).

## Scaffold defects found and repaired in SCAFFOLD.yaml
1. **`ERR_DUES_NOT_CURRENT` was unreachable** (found while designing its recipe): the sweep suspends any DELINQUENT membership, so priority-25 `ERR_MEMBERSHIP_NOT_ACTIVE` always shadowed it, and the `ACTIVE -> TRANSFER_PENDING` / `TRANSFER_PENDING -> TERMINATED` preconditions demanded `dues_status == CURRENT` with no declared error. Validation 42's `check` and `applies_to` (now including `POST /transfer-requests/{id}/decision`) and the catalogue condition were widened, making a GRACE membership's transfer submission *and* decision both 409.
2. **Validation 33 contradicted the extension endpoint**: `ERR_STAY_LENGTH_EXCEEDED` applied to `POST /reservations/{id}/extensions`, yet that endpoint routes an over-limit merged run to `EXTENSION_REVIEW` instead of raising. The check and catalogue condition now state the carve-out explicitly (only the affiliate `per_stay_night_cap` half can raise there).
3. **State machine vs. §1.5 mismatch on extensions**: the transitions spoke of `body.additional_nights` and "departure_date is NOT changed yet", while §1.5/§1.8 use `new_departure_date` set immediately with rollback on DENY. All four affected transition entries were rewritten to the `new_departure_date` convention (including the partial-grant formula note).
4. **Dead scope rule**: `POST /occupancy-exceptions/{id}/decision` was removed from validation 4's `applies_to` (that endpoint's roles are ComplianceOfficer-only, so the ParkManager clause was vacuous).

Also normalised all 20 `difficulty_instance:` citations to the SKILL's `category / name` form (the file previously mixed bare and compound forms), and fixed two capture forms (`$.total_count` → a `$.data[N].field` capture; `rbac.<Role>` grounds → `roles[<Role>]`).

Orchestrator verification: all three files parse as valid YAML; SCAFFOLD.yaml contains neither design key; DIFFICULTY/CORNER each contain exactly their single required top-level key.

## Step 3: Copy shared files — 2026-09-03T21:45:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2611_membership_campground_recreational_vehicle_club_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T22:01:00.000Z

All checks clean. PRD.md is complete and verified.

## Deliverable

`.../workspace/PRD.md` — **454 lines**, built incrementally (1 `Write` + 8 quoted-heredoc `cat >>` appends + 2 targeted `Edit` repairs), every append verified with `wc -l` / `tail`. No truncation; the file ends at a real section boundary (the final row of the §5 table). No audit footer written into the file.

Structure (deliberately divergent from `example-prd.md`'s skeleton — 10 §2 subsections and 9 §3 subsections with domain-specific titles):
- §1 Introduction (3 paragraphs)
- §2.1 RBAC · §2.2 Response Structure (verbatim fixed block) · §2.3 Pagination · §2.4 Identity/Audit/Logical Clock · §2.5 Nested Read Paths · §2.6 Money, Nights & Rounding · §2.7 OCC on Membership and Park Writes · §2.8 The Validation Ladder (all 48 rungs in evaluation order) · §2.9 Counter Conservation & Cascade Integrity · §2.10 Half-Open Stays & Closed Maintenance Intervals
- §3.1 Tiers & Membership Sale · §3.2 Park Network / Capacity Split / Seasons / Affiliates · §3.3 Member Booking (PENDING → CONFIRMED|WAITLISTED) · §3.4 Transient Booking & Nightly Pricing · §3.5 Occupancy in Progress (arrival, extension, exception review, departure) · §3.6 Releases (cancellation, maintenance, waitlist) · §3.7 Billing Axis (dues, delinquency, suspension, reinstatement) · §3.8 Transfer, Resale, Succession · §3.9 Surveys, Amenity Standards, Capital Reinvestment
- §4 Endpoint Definitions — 55 rows, exactly 4 columns
- §5 Error Code Catalogue — 48 rows, exactly 2 columns

## Hard Contract 1 — Field-Name Coverage: **PASS**
- `entities[].fields`: 131 required, 131 present, 0 missing (13 entities)
- `endpoints[].request_body`: 87 required, 87 present, 0 missing
- `endpoints[].query_params`: 23 required, 23 present, 0 missing
- `errors[].id`: 48/48 present · `roles`: 5/5 present · all state-machine state values present · all field `enum` members present · path param and both `occ_field`/`error_id` pairs present

One gap was caught and repaired on the second pass: `OccupancyException.reason` members `MEDICAL`, `EMPLOYMENT`, `WEATHER` were absent (only the `RIG_REPAIR` default appeared). Fixed in §3.5; re-run returned `enum missing: []`.

## Hard Contract 2 — Rule Coverage: **PASS**
- **Validation priorities (48/48):** every rung enumerated in §2.8 in scaffold priority order with its error ID and its complete `applies_to` endpoint scope. The masking consequences of rungs 41 and 42 are called out explicitly in two dedicated paragraphs.
- **Concurrency (2/2):** `expected_membership_version` → `ERR_STALE_MEMBERSHIP_VERSION` (412) on transfer submission; `expected_park_version` → `ERR_STALE_PARK_VERSION` (412) on capital-project decision. §2.7 states which writes do *not* take a version token.
- **State transitions (54/54)** across all 10 machines, including both parallel Membership axes (`membership_status` × `dues_status`), the 13 Reservation transitions, and the DuesInvoice `PAID → OPEN` / `PAID → PAST_DUE` reversal branches.
- **Calculations (15/15)** translated to operator-free prose with exact constants. Verified mechanically: every constant *value* in the scaffold is recoverable from the prose (the only two not present as raw literals are `07-01`/`09-07`, rendered as "July 1st"/"September 7th" per the no-pseudocode rule).
- **Side effects:** all `endpoints[].side_effects` covered, including the 5-link maintenance-activation cascade and the 6-link delinquency cascade.
- **Sibling-branch symmetry:** both extension branches, transfer APPROVE/REJECT, exception GRANT/DENY, capital FUNDED/DEFERRED, PENDING→CONFIRMED vs WAITLISTED, member vs transient allocation, and both payment-reversal target states.
- **Field defaults:** a second repair added the reservation counter initial values (`pool_charged` = `NONE`; `entitlement_nights_charged`, `affiliate_nights_charged`, `total_charge_cents`, `extension_count`, `extension_denied_count`, `consecutive_run_nights` = 0; `cancellation_reason`, `checked_in_at`, `checked_out_at` = null), which §3.3 had previously left implicit.

## Hard Contract 3 — §3 Path Purity: **PASS**
1,071 backtick tokens scanned in §3: 0 leading-slash paths, 0 bare HTTP methods, 0 method+path pairs, 0 unbacked stray `/x-y` path text. §3 uses state-transition, role+action-verb, and capability framing throughout.

## Notes for downstream steps
- The hard constraint was honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.
- **One scaffold gap worth flagging:** the `CapitalProject PROPOSED → APPROVED` transition carries a precondition (park's `amenity_compliance_status` is not `NON_COMPLIANT`, OR `category` is `SAFETY` or `UTILITY`) but no `error_id` is assigned to it anywhere in the scaffold. Rather than invent an error code, I expressed it as a prose business constraint with no nominated error. If the hidden suite asserts a specific error ID here, the scaffold needs the ID added.
- **One internal scaffold divergence reconciled:** the Membership-suspension side effects in `state_machines` filter reservations by `arrival_date >` the current logical date, while the same suspension's `endpoints[].side_effects` list includes `PENDING` without that filter. §3.7 covers both readings ("those in `PENDING`, `CONFIRMED` or `WAITLISTED` with an `arrival_date` after the current logical date").

Orchestrator anti-truncation verification: 454 lines / 108,441 bytes; headings present for §1–§5 including all 10 §2 and all 9 §3 subsections; §4 table carries 55 endpoint rows (matching scaffold's 55) and §5 carries 48 error rows (matching scaffold's 48); file ends on the complete final table row `| ERR_REINSTATEMENT_FEE_REQUIRED | 422 |` — a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T22:36:00.000Z

The implementation is complete and verified.

## Deliverable
`.../workspace/implementation/`

| file | lines |
|---|---|
| app.py | 67 |
| auth.py | 66 |
| calc.py | 288 |
| clock.py | 95 |
| engine.py | 645 |
| errors.py | 64 |
| guards.py | 41 |
| response.py | 83 |
| routes_capital.py | 168 |
| routes_catalog.py | 424 |
| routes_parks.py | 365 |
| routes_reservations.py | 593 |
| routes_transfers.py | 181 |
| serializers.py | 242 |
| store.py | 91 |
| validators.py | 143 |
| start.sh | 10 |
| requirements.txt | 1 |
| **total** | **3567** |

## Verification performed
- `python3 -m py_compile *.py` → COMPILE_OK on all 16 modules; `__pycache__/` removed afterwards.
- Live HTTP smoke test: launched `PORT=18611 bash start.sh` in the background, then curled four endpoints. `GET /membership-tiers` → 200 with an empty `data: []` and full list `meta` (`api_request_id` `req_` + 20 uppercase alnum, `api_request_timestamp` `2026-08-01T00:00:00.000Z`, `limit`/`offset`/`total_count`/`has_more`), `response_type: "array"`. `POST /membership-tiers` → 201 with `response_type: "object"` and the full persisted row. Header-less `GET /parks` → 401 `ERR_UNAUTHENTICATED` with `response_type: "error"`. `GET /memberships/nope` → 404 `ERR_MEMBERSHIP_NOT_FOUND`.
- Server shut down safely: resolved the single listener PID via `ss -ltnp | grep ':18611'` (pid 2438627) and killed only that pid; confirmed port 18611 free. No pattern-kill was used at any point.

## Design notes worth relaying
- Storage is in-memory only — 13 dicts in `store.py`, `store.reset()` + `clock.reset()` run inside `create_app()`, so every per-test reboot starts with empty collections and the clock at `2026-08-01T00:00:00Z`. A grep for `sqlite3`, `open(`, `json.dump`, and `/tmp` across all modules returns nothing.
- The 48-rung ladder is implemented in strict numeric order. Because existence rungs (5–15) precede body well-formedness (16), FK reads use `v.raw_id()` + `guards.maybe()`: a present-but-unknown id 404s, while an absent field falls through to `ERR_INVALID_REQUEST`. Ownership rungs (3/4) are `guards.find()` → `auth.require_*()` → `guards.fetch()`.
- All pinned constants live in `calc.py`; money and scores use `Decimal` with `ROUND_HALF_UP`. The PRD's own worked examples were checked end-to-end in a prior in-process run through the Flask test client (23 flows): dues 61560, transient 20985 (per-night rounding 9626 ×2 + 1733), survey 4.25, inspection 4.20 PASS, priority_score 1872, GIFT fee 10000, granted-exception departure 2026-07-20 with 12 nights at check-out.
- Where the SCAFFOLD declared no dedicated error id, I mapped pragmatically: non-PROPOSED capital-project decision and the NON_COMPLIANT approval restriction → `ERR_INVALID_REQUEST`; check-in outside the date window → `ERR_INVALID_RESERVATION_STATE`; out-of-range `actual_departure_date` → `ERR_INVALID_REQUEST`; all three reinstatement preconditions → `ERR_REINSTATEMENT_FEE_REQUIRED`.
- Two spec conflicts were resolved in favour of PRD prose: season closure expires **all** WAITLISTED rows (no arrival filter) and counts only cancelled CONFIRMED rows toward `forced_cancellation_count`, whereas maintenance activation counts every cancelled row.
- `GET /parks/{id}/amenity-inspections` is the one declared ordering exception (newest-first by `inspected_at` desc); every other list uses the standard `created_at`/insertion order.

I did not read or write anything under `test_helpers/` or `test_suite/`, and did not look at sibling tasks — generation came solely from INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator ran while `test_suite/` did not yet exist on disk — physical isolation held.

## Step 5: Generate unit tests — 2026-09-03T23:20:00.000Z

Queue B is complete and the whole suite now passes every mechanical audit.

## What was added this pass

`.../test_suite/`
- `test_corner_rbac.py` — 435 lines, 4 tests (role gates outranking existence/domain rules with positive controls; five `ERR_NOT_RESOURCE_OWNER` probes vs. ClubAdmin reads; six `ERR_NOT_PARK_MANAGER` writes at a neighbouring park while reads stay open; segregation of duties on both a transfer decision and two capital projects, proving the comparison is on `X-User-ID` and blind to the role header).
- `test_corner_cross_cutting.py` — 344 lines, 4 tests (dues payment invalidating a pinned membership version → `ERR_STALE_MEMBERSHIP_VERSION` 412 with versions 1→2→3; inspection invalidating a pinned park version, with priority 18 beating priority 41 on a call that violates both, score 4200→5460; one sweep landing six memberships on the 0/1/29/30/119/120-day boundaries; a cured invoice that two later sweeps leave untouched).
- `test_corner_consistency.py` — 196 lines, 2 tests (one survey publishing `weighted_score` 4.60, `rating_score` 0.00→4.60 and both project scores 4200→1686 / 2000→803 in the same request, with the check-out proving a non-trigger stays a non-trigger; a cancellation publishing the promoted stay, its debits and an empty waitlist on the very next read).

## Coverage

- Corner index: 56 non-stub instances, all translated (57 tests); the 20 `excluded_because:` stubs were never touched.
- Difficulty index: 18 instances, each with ≥2 tests (36 tests).
- 93 tests total, each with exactly one verbatim `Design:` line as the last docstring line, all resolving to real non-stub instances. No skip/xfail anywhere. `python3 -m py_compile` clean on all 19 `test_suite/*.py` and all 9 `test_helpers/*.py`; zero unused `test_helpers` imports and zero undefined globals across the suite.

## Findings worth relaying

1. **A citation audit caught 15 paraphrased PRD quotes** (14 in the earlier difficulty files, 1 in rbac) that were not greppable in `workspace/PRD.md` — several were scaffold-style rule text rather than PRD prose. All 15 were replaced with verbatim PRD sentences sliced directly out of the file (`ERR_ADVANCE_WINDOW_EXCEEDED`, trailing-window 180-day drop, cancellation compensating action, entitlement-year counter derivation, payment reversal, `ERR_PARK_NOT_OPEN` ladder row 28, season opening, reciprocity ceiling, agreement suspension, run-merge link gap, half-open nights, waitlist debits nothing, ParkManager scope). All 96 docstring quotes now verify verbatim against the PRD.
2. **Two design recipes specify non-integer amenity scores** (`4.50` in rbac, `4.80/4.60/4.40/4.20` in the stale-park instance). PRD §3.9 requires integers 1–5 and body well-formedness is rung 16, below the rung-4 scope rule, so integers were used instead (`4`s for the scope probe; `2`s for the stale-park probe, which additionally makes the recipe's own "the score was re-scored" assertion true — a PASS would have left 4200 unchanged, whereas the FAIL band gives 4200 → 5460).
3. **One design assertion contradicts the PRD and was omitted:** the six-row sweep recipe asserts `dues_balance_cents` 48082 on the 120-day row, but PRD §3.1 states invoices in `PAID` or `WRITTEN_OFF` contribute nothing to `dues_balance_cents`. Everything else on that row is asserted (invoice `WRITTEN_OFF`, `late_fee_cents` 2722, dues `WRITTEN_OFF`, membership `TERMINATED`). `memberships_to_delinquent` was also left unasserted on that sweep, since the PRD does not settle whether the row that continues on to write-off is also tallied there; `invoices_swept` 6, `memberships_to_grace` 2 and `memberships_written_off` 1 are asserted.

Orchestrator verification: `test_helpers/` (9 files) and `test_suite/` (19 files) both exist at the TASK ROOT; neither `workspace/test_helpers` nor `workspace/test_suite` exists, so no relocation was needed. 93 `Design:` tags counted across `test_suite/*.py`, matching the reported test count.

## Step 7: Run tests and iterate — 2026-09-03T23:34:00.000Z

Done — the suite is genuinely green.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps.

- **Iteration 1:** 92/93 in all 8 rounds. Exactly one test failed, deterministically in every round (not flakiness, not load): `test_corner_cross_cutting.py::test_one_sweep_lands_six_memberships_on_the_three_ageing_bands` — `AssertionError: a row merely due today is not rewritten at all; assert 2 == 1`.
- **Iteration 2 (after fix):** all 8 rounds `passed == total == 93`, `failed == 0`, `errors == 0`.

Final pass counts, read from the per-round files in `.../workspace/implementation/`:

| round | passed | failed | total |
|---|---|---|---|
| results.1.json | 93 | 0 | 93 |
| results.2.json | 93 | 0 | 93 |
| results.3.json | 93 | 0 | 93 |
| results.4.json | 93 | 0 | 93 |
| results.5.json | 93 | 0 | 93 |
| results.6.json | 93 | 0 | 93 |
| results.7.json | 93 | 0 | 93 |
| results.8.json | 93 | 0 | 93 |

**Tests deleted:** none. The single failure passed both STEP 1 sub-checks — PRD §2.4 verbatim: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row", and §3.7 scopes the sweep's membership bumps to the band advances: "Each of these advances increments the membership's `version` by 1." A membership whose invoice is merely due today (`days_past_due == 0`, status stays `OPEN`, `late_fee_cents` stays 0, so its derived `dues_balance_cents` is unchanged) undergoes no advance and no field change, so no faithful reader can bump its version. Unique derivability holds.

**Fixes applied to `test_helpers/`:** none. STEP 2 audit found the fixture chain (`sell_membership_to_new_member`, `run_delinquency_sweep`, `read_membership`) faithful to PRD — sale dates staggered against a fixed sweep instant, `ClubAdmin` identity on the sweep, and `Member`-row ids for member headers.

**Fixes applied to `implementation/`:** one, in `.../workspace/implementation/routes_catalog.py`, in `dues_delinquency_run()` — the final reconciliation loop called `store.touch(membership)` unconditionally for every membership holding an `OPEN` or `PAST_DUE` invoice, incrementing `version` and `updated_at` on rows the sweep had left completely unchanged. It now snapshots each membership's content before the sweep and touches only rows whose business columns actually moved, via a new `_content_changed()` helper that ignores the `version`/`updated_at` audit columns. Rows the sweep genuinely mutates (band advances, the delinquency cascade, write-off, late-fee-driven `dues_balance_cents` movement) keep their prior bump behaviour exactly, so no PRD-required counter movement was weakened.

No test was skipped, xfailed, weakened, or deleted; no implementation check was removed; storage remains in-memory only.

Orchestrator independent verification (not taken on trust): all 8 `results.$i.json` exist on disk, each parses as JSON with `passed=93 failed=0 total=93 errors=0`, and each contains 93 test records all with `status: "passed"`. File mtimes (23:28) post-date the `routes_catalog.py` fix (23:24:42), so the green sweep reflects the fixed code rather than a stale run. A grep for `skip`/`xfail` across `test_suite/` and `test_helpers/` returns only 12 incidental prose/variable-name matches — zero `pytest.mark.skip` or `pytest.mark.xfail` decorators. 93 tests remain, matching Step 5's output count, confirming the zero-deletion claim.

## Step 8: Finalize PRD — 2026-09-03T23:41:00.000Z

Done. One edit, tracing to the single `implementation/` fix in `<step_7_diff>`.

## Line counts
- `PRD.md`: 454 lines / 108,441 bytes
- `PRD_FINALIZED.md`: 454 lines (0.0% line delta); 1 line revised (0.22% of lines), +1,201 bytes (+1.1%)

## Change
- **§3.7 (The Billing Axis), "Three ageing bands…" paragraph — insert (appended after the existing verbatim sentence, nothing removed)** — pins (a) that the sweep recomputes `dues_balance_cents` and `tenure_years` on every membership holding a swept `OPEN`/`PAST_DUE` invoice, skipping one already `WRITTEN_OFF` when the sweep reached that invoice; (b) that a membership row is rewritten (`updated_at`/`version`) only where the sweep actually moved a stored business field, with a band advance, the cascade, the write-off and a late-fee-driven `dues_balance_cents` shift all named as movement; (c) that a membership left byte-identical (the invoice-merely-due-today holder) is not rewritten at all; (d) the contrasting asymmetry that every swept invoice *is* rewritten even when `days_past_due` is unchanged — `implementation/routes_catalog.py:372-376` (`_content_changed`), `:394-397` (pre-sweep snapshot), `:408` (unconditional invoice touch), `:410-413` (`WRITTEN_OFF` skip / `touched` set), `:432-437` (reconciliation loop).

## Pre-edit search log
**(a) Subject:** which rows the delinquency sweep rewrites, i.e. membership/invoice `version`+`updated_at` movement inside `/ops/dues-delinquency-run`, plus the sweep's recompute of the membership's derived `dues_balance_cents`/`tenure_years`.

**(b) Impl paths enumerated (read or grepped):**
- `implementation/routes_catalog.py:379-439` `dues_delinquency_run` — invoice loop, waitlist-expiry loop, final reconciliation loop.
- `implementation/routes_catalog.py:343-357` `_delinquency_cascade` and `:359-369` `_write_off` — neither touches the membership row itself.
- `implementation/engine.py:625-645` `suspend_cascade` → `force_cancel` (`:385-392`) → `release_debits` (`:340-382`), which **does** `store.touch(membership)` at `:371` once per cancelled reservation carrying entitlement nights.
- `implementation/engine.py:398-419` `_promote` (via `waitlist_sweep` `:422+`), which `store.touch(membership)` at `:419` for a promoted holder.
- `implementation/engine.py:611-622` `void_submitted_transfers` (touches the request only); `add_quota`/`credit_quota` `:342-355` (touch the agreement only).
- `implementation/store.py` `touch`/`base_row` — `version` starts at 1, +1 per touch.
- All other `recompute_dues_balance`/`recompute_tenure` callsites: `routes_catalog.py:135, 203, 214, 270, 302, 335-336`, `routes_transfers.py:135`, `engine.py:588, 606`, and `serializers.py:47` (membership reads recompute `tenure_years` **without** touching the row).
- `PRD.md` §2.4 (audit columns), §2.7 (version preconditions), §3.7 payment/reversal/suspend/reinstate paragraphs, §4 row for `/ops/dues-delinquency-run` (no version detail there).

**(c) Wording adjustments forced by that search:**
1. My first draft asserted the sweep moves an advancing membership's `version` "by exactly 1 for the sweep, even when it crosses two bands in one pass." `engine.py:371` and `:419` disprove that — a cascading membership is additionally touched once per released reservation, and a waitlist-promoted holder once more. I dropped the per-sweep count entirely and wrote only the necessary condition ("rewritten only where a stored business field moved"), leaving the number of increments under-determined.
2. Scoped the rewrite rule with "Within the sweep" so it cannot be read as narrowing the unconditional `store.touch` in the annual dues run, payment, reversal, suspend, reinstate or transfer-decision paths (all of which always mutate anyway).
3. Kept the `WRITTEN_OFF` exclusion phrased as "already sitting at `WRITTEN_OFF` when the sweep reached its invoice" rather than "before the run", because `:411` re-reads live state and so also skips a membership written off earlier in the same pass — while the row written off *during* the pass is still in `touched` and does get rewritten.
4. Stated the invoice side explicitly and separately ("carry no such condition") so a fresh implementer does not generalise the changed-only rule from memberships to invoices, which `:408` contradicts.

Orchestrator verification: `PRD_FINALIZED.md` exists at 454 lines / 109,628 bytes; `diff PRD.md PRD_FINALIZED.md` reports exactly 2 changed lines (1 removed, 1 added — a single in-paragraph revision), confirming the patch is minimal and that the file is not a byte-identical copy. Step 8 was not skipped because Step 7 applied 1 `implementation/` fix.

## Step 9: Complete PRD — 2026-09-04T00:02:00.000Z

Pass C complete, and the mandatory final check has been run.

## Final check (mandatory)

```
diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l   →  172
wc -l -c PRD_FINALIZED.md   →  454 lines / 109,628 bytes
wc -l -c PRD_COMPLETED.md   →  454 lines / 126,875 bytes
```

Line count unchanged (454 → 454), char delta **+17,247**. 43 paragraphs changed, 48 distinct semantic patches, delivered by 55 `Edit` calls. No new sections, no new paragraphs — every patch is in-paragraph.

## Per-pass module reads / edits

| Pass | Modules read (lines) | Edit calls |
|---|---|---|
| A | app.py 67, store.py 91, clock.py 95, errors.py 64, response.py 83, auth.py 66, guards.py 41, validators.py 143, serializers.py 242, routes_catalog.py 439 | 14 |
| B | calc.py 288, engine.py 645 | 10 |
| C | routes_parks.py 365, routes_reservations.py 593, routes_transfers.py 181, routes_capital.py 168, start.sh 10, requirements.txt 1 | 31 |

calc.py turned out to be a faithful implementation of every PRD formula — no patch originated from it. start.sh/requirements.txt make no claim the PRD contradicts (`PORT` default 10000, `0.0.0.0`, foreground `exec python3 app.py`), so the boot contract needed no patch.

## Tally

- **Mismatch-revisions: 18**
- **Ambiguity-pins: 30**

## One bullet per change

- §2.3 — insert — ambiguity — pagination faults pinned: non-integer / `limit` outside 1–100 / negative `offset` → `ERR_INVALID_REQUEST` 400, empty string treated as omitted — response.py:56
- §2.3 — insert — ambiguity — global tie-break is the server's insertion sequence — store.py:86
- §2.3 — revise — ambiguity — the inspection list's ties break *descending* (the ascending order simply reversed) — routes_parks.py:174
- §2.8 — insert — ambiguity — the clock hook is exempt from rung 1 but answers `ERR_UNAUTHORIZED` for an out-of-set role — auth.py:44
- §2.8 — insert — ambiguity — rung 3 bites only for `Member` on a resource that resolves to a membership; `TransientGuest` is never owner-checked — auth.py:53
- §2.8 — revise — mismatch — rung 20 also covers check-in, maintenance activation and completion, and sits *after* rung 21 on the maintenance pair — routes_reservations.py:291, routes_parks.py:257
- §2.8 — revise — mismatch — rung 25 also covers check-in and direct suspension — routes_reservations.py:294, routes_catalog.py:198
- §2.9 — insert — ambiguity — any quota movement bumps the agreement's `version`; a 0-night movement is a no-op; credits floor at 0 — engine.py:342,350
- §2.10 — revise — mismatch — `effective_from`/`effective_to` are recorded but never enforced at booking or extension; only `status` gates — routes_reservations.py:75
- §3.1 — revise — mismatch — tier `code` uniqueness is not enforced — routes_catalog.py:30
- §3.1 — revise — mismatch — member `email` uniqueness is not enforced — routes_catalog.py:75
- §3.1 — insert — ambiguity — `tenure_years` re-derived on every read without moving `version`/`updated_at` — serializers.py:47
- §3.1 — insert — ambiguity — `dues_paid_through` starts null on a newly sold contract — routes_catalog.py:128
- §3.2 — revise — ambiguity — an `ACTIVE` window blocking a season opening shares `ERR_INVALID_PARK_STATE`; order is status → date band → window scan — routes_parks.py:83
- §3.2 — insert — ambiguity — season closure stamps `SEASON_CLOSURE` on `WAITLISTED` rows too, regardless of arrival date — routes_parks.py:117
- §3.2 — revise — mismatch — `partner_name` uniqueness is not enforced — routes_parks.py:315
- §3.2 — revise — mismatch — `per_stay_night_cap` is bounded 1–45, not 1–30 — routes_parks.py:322
- §3.2 — revise — ambiguity — `effective_to` ≥ `effective_from` (equal allowed) → `ERR_INVALID_REQUEST` — routes_parks.py:325
- §3.3 — revise — ambiguity — merged-run ordering breaks ties by insertion sequence, the candidate sorting last — engine.py:161
- §3.3 — revise — ambiguity — occupancy-run scan tie-break by insertion sequence — engine.py:161
- §3.3 — insert — ambiguity — a member booking never bumps the park's `version`; a `WAITLISTED` booking bumps nothing — routes_reservations.py:130
- §3.5 — revise — ambiguity — check-in error ids and their order: reservation status, park status, membership status, date band — routes_reservations.py:289
- §3.5 — insert — ambiguity — a `ParkManager` is unscoped on check-in/check-out — auth.py:53
- §3.5 — insert — ambiguity — `new_departure_date` must strictly extend (`ERR_INVALID_REQUEST`); the rule list is not an order; which quantity each rule measures — routes_reservations.py:373
- §3.5 — revise — mismatch — extension debits the quota by `ceil(new nights × ratio) − affiliate_nights_charged`, not by the added nights — routes_reservations.py:417
- §3.5 — insert — ambiguity — the review branch recomputes `nights`, bumps the membership `version` anyway, and retains the pre-extension date internally — routes_reservations.py:440
- §3.5 — insert — ambiguity — `granted_run_nights` ≥ 1; below `tier_limit_nights` → `ERR_INVALID_REQUEST` *before* the already-decided rung; delta-gated headroom; short grant → `ERR_INVALID_REQUEST`; both branches return the exception — routes_reservations.py:518
- §3.5 — revise — mismatch — a grant rewrites `entitlement_nights_charged` absolutely and skips both debits when the delta is not positive — routes_reservations.py:576
- §3.5 — insert — ambiguity — a denial recomputes `nights`, falls back to the current date if the retained one is gone, and bumps the membership `version` — routes_reservations.py:536
- §3.5 — revise — mismatch — check-out frees the seat for the *whole* stay (a `COMPLETED` row occupies nothing), leaves `pool_charged` set, and sweeps unconditionally and unrestricted — routes_reservations.py:351, engine.py:114
- §3.5 — insert — ambiguity — a bad `actual_departure_date` → `ERR_INVALID_REQUEST`, after the `CHECKED_IN` check — routes_reservations.py:322
- §3.6 — insert — ambiguity — the cancellation sweep is unrestricted; a cancelled `TRANSIENT_POOL` booking triggers none — routes_reservations.py:275, engine.py:379
- §3.6 — revise — ambiguity — waitlist ordering breaks remaining ties by insertion sequence — engine.py:434
- §3.6 — revise — mismatch — promotion re-tests entitlement but never partner quota, so a promotion can overshoot `annual_member_night_quota` — engine.py:406
- §3.6 — insert — ambiguity — `end_date` ≥ `start_date` (equal = one-night window) → `ERR_INVALID_REQUEST` — routes_parks.py:230
- §3.6 — insert — mismatch — `forced_cancellation_count` is bucketed by logical calendar year and resets across a New Year — engine.py:466
- §3.7 — revise — mismatch — the annual dues run skips `TERMINATED` and `WRITTEN_OFF` memberships and rolls the year on `entitlement_year_start + 365` — routes_catalog.py:319
- §3.7 — insert — ambiguity — one sweep can drive a membership through both bands, counting it in `memberships_to_delinquent` *and* `memberships_written_off` — routes_catalog.py:411
- §3.7 — revise — mismatch — suspension cascade statuses and reason strings pinned; the transfer/reservation leg applies no arrival-date filter — engine.py:385, routes_catalog.py:437
- §3.7 — revise — mismatch — `reason` accepted as an alias for `suspension_reason`; refusal id and ordering; `VOIDED` reason string — routes_catalog.py:195
- §3.7 — revise — mismatch — the four reinstatement preconditions collapse into one `ERR_REINSTATEMENT_FEE_REQUIRED`; balance recomputed first; the fee is stored nowhere — routes_catalog.py:219
- §3.8 — insert — ambiguity — non-zero `sale_price_cents` on a non-`RESALE` → `ERR_INVALID_REQUEST` — routes_transfers.py:36
- §3.8 — insert — ambiguity — the submitting `X-User-ID` is kept internally for the segregation check and never serialised — routes_transfers.py:81
- §3.8 — insert — ambiguity — successor mints `upfront_paid_cents` 0, a today-dated `entitlement_year_start` and a fresh `resale_eligible_at`; rejection keeps the frozen fee; both branches return the `TransferRequest` — routes_transfers.py:110
- §3.9 — revise — mismatch — `requested_cost_cents` ≥ 0 (not ≥ 1) and `fiscal_year` merely non-negative (not 2020–2100) — routes_capital.py:32
- §3.9 — revise — mismatch — non-`PROPOSED` → `ERR_INVALID_REQUEST`; order is version pin → `PROPOSED` → segregation → compliance; the compliance refusal is also `ERR_INVALID_REQUEST`; the project `version` always bumps; `decision_note` is internal — routes_capital.py:72
- §3.9 — revise — ambiguity — reinvestment ordering adds an insertion-sequence tie-break; `budget_cents`/`fiscal_year` only non-negative; a candidate with a missing park is skipped — routes_capital.py:99
- §4 — insert — ambiguity — a multi-row mutation always returns the resource named in the path (enumerated per operation), the ops runs and the clock hook excepted, the latter echoing the single normalised `current_utc` — routes_capital.py:160
- §5 — insert — ambiguity — `ERR_INVALID_REQUEST` is also emitted at HTTP 404 (unrouted path) and 405 (bad method) — app.py:45

Read prohibitions honored throughout: no `SCAFFOLD*.yaml`, no `worklog.md`. Tests were used only as auxiliary cross-reference; every patch traces to `implementation/`.

Orchestrator verification: `PRD_COMPLETED.md` exists at 454 lines / 126,875 bytes; `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` = 172 (non-zero, so the scan genuinely ran) and the two files' md5 sums differ (`3d01f47c…` vs `f5ad207b…`), ruling out the byte-identical-copy failure mode. All 27 markdown headings are preserved and the file still ends on the final §5 error-table row, so no section was lost while patching. PIPELINE COMPLETE.
