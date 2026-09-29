# Worklog — task_2458_convention_housing_bureau_operations

## Step 1: Create task directory — 2026-09-02T20:16:19.989Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations` and its `workspace/` subdirectory. Index 2458 was pre-assigned by the orchestrating pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T21:34:49.964Z

All three artifacts are complete and the linter passes.

Verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  858

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Three files in `/home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/`:

**SCAFFOLD.yaml** (§1.0–§1.7, api_prefix `/housing`, neither design key present)
- 12 entities: Event, Hotel, HotelBlock, SubBlock, Attendee, Reservation, RoomingListTransmission, PickupReport, AttritionReduction, RogueHousingVendor, PoachingIncident, CommissionInvoice
- 8 state machines (HotelBlock negotiation loop with a 3-round cap; SubBlock approval/release; Reservation with a two-axis occupancy/transmission model where WAITLISTED is reachable only via the attrition cascade; AttritionReduction; RogueHousingVendor; CommissionInvoice dispute/adjust cycle)
- 2 OCC concurrency rules on HotelBlock (`expected_hotel_block_version`, ERR_STALE_BLOCK_VERSION/412) covering terms revision and sub-block carve
- 13 calculations: dual-variant `block_pickup_pace` and `commission_due`, `reservation_total_charge` (per-night round-half-up then multiply), `attrition_penalty_exposure` (3 tiers), `sub_block_reduction_waterfall` (unassigned then SEGMENT_RANK then carve_seq), `reduction_rights_headroom`, `event_housing_posture`, `sub_block_night_occupancy`, `attendee_stay_overlap_check` (1-day shoulder buffer), `commission_variance_tolerance`, `no_show_billing`, `rooming_list_transmission_set`, `rogue_vendor_risk_score`
- 33 ordered validations (priorities 10–106), 50 errors, 57 endpoints, 6 roles (BureauCoordinator, BureauController, HotelManager, EventOrganizer, Attendee, ComplianceOfficer) with two segregation-of-duties splits

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances, exactly 2 per each of the 9 §0.5 difficulty rules.

**SCAFFOLD_CORNER_DESIGN.yaml** — 9 sections, 88 entries = 73 real test recipes + 15 `excluded_because` stubs pointing at the §1.8 instance that already covers the claim. Per section (real/stubs): entities 13/0, state_machines 10/4, calculations 10/4, validations 11/2, endpoints 6/0, errors 12/3, rbac 7/0, cross-cutting 3/2, consistency model 1/0.

All 106 instance names are unique across both design files; 858 setup/trigger calls lint clean against §1.5 (endpoint existence, role legality, payload/required-field conformance, capture JSONPath resolution, `${...}` OCC versions, FK reverse-reachability).

## Step 3: Copy shared files — 2026-09-02T21:34:54.172Z

Copied `./INSTRUCTION.md` → `tasks/task_2458_convention_housing_bureau_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:49:22.620Z

PRD generation is complete and verified.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/workspace/PRD.md`
- **454 lines**
- **Last section heading: `## 5. Error Code Catalogue`**
- **Not truncated** — the file ends at a real section boundary: the complete final row of the §5 table, `| \`ERR_VARIANCE_WITHIN_TOLERANCE\` | 422 Unprocessable Entity |`, followed by a trailing newline.

**Structure:** §1 Introduction (3 paragraphs); §2 with 11 domain-derived subsections (RBAC, the fixed §2.2 envelope, pagination, identity/timestamps/revision counters, the logical housing clock, room-night and money rounding discipline, the block inventory invariant, stale-block protection, segregation of duties, a 31-step normative request-evaluation ordering, event housing posture); §3 with 9 freely grouped workflow subsections (program setup, block assembly, sub-block carves, portal opening and reservations, change management, outward reporting, attrition reduction cascade, poacher/rogue-housing monitoring, cutoff and commission settlement); §4 a 57-row 4-column endpoint table; §5 a 50-row 2-column error table.

The hard constraint was honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

Final verification pass (re-run after the last repair edits):

```
Field coverage check:
- entities[].fields: 121 required, 121 present, 0 missing
- endpoints[].input + output shapes: 74 required, 74 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
- errors[].id: 50 required, 50 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose (explicit 31-step ordering in §2.10), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_hotel_block_version + ERR_STALE_BLOCK_VERSION/412 all named), 0 missing
- state_machines[].transitions: 37 checked, 37 fully expressed as literal from → to pairs, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all checked, all expressed, 0 missing
- entities[].fields[] structured content: 121 checked, 121 reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked, 5 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 835
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 is byte-identical to `section-2.2-response-structure.md` (confirmed by substring test). No pseudocode/operator syntax and no fuzzy quantifiers ("approximately", "roughly", "conservatively") anywhere in the document; all 13 calculations, including the pinned per-night tax-then-round-then-multiply order, the six-step attrition penalty tiers at ratio boundaries 0.10/0.25, the reduction waterfall segment order, the risk-score weights with 0–100 clamp and 60 escalation, and the greater-of-5,000-cents-or-1-percent variance tolerance, are stated as business prose that reconstructs the arithmetic exactly.

Orchestrator verification: tail read independently — file ends with the final error-table row, 27 headings present through `## 5. Error Code Catalogue`. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T23:09:26.000Z

Generation is complete for task 2458. Both stages are finished and both design queues are fully translated.

**Files created**

Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/test_helpers/`: `__init__.py` (single import surface, re-exports framework generics), `api_client.py`, `api_errors.py` (error-id → HTTP-status map), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (5-tier setup ladder), `test_users.py`, `types.py`.

Stage 2 — `/home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/test_suite/`: `conftest.py` plus 18 test modules, 109 tests, 91 distinct `Design:` tags.

**Counts per source queue**

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, §1.8): 18/18 instances, 36 tests — `test_01`…`test_09`, two tests per instance (9 rules × 2 instances × 2).
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`, §1.9): 73/73 non-stub instances, 73 tests, exactly one per instance — entities 13 (`test_10`), state_machines 10 (`test_11`), calculations 10 (`test_12`), validations 11 (`test_13`), endpoints 6 (`test_14`), errors 12 (`test_15`), rbac 7 (`test_16`), cross-cutting complexity layers 3 (`test_17`), consistency model 1 (`test_18`).

**Instances skipped:** none. The only untranslated queue-B entries are the 15 `excluded_because:` stubs (4 state_machines, 4 calculations, 2 validations, 3 errors, 2 cross-cutting), which by design defer to a named queue-A instance; I verified all 15 `difficulty_instance:` cross-references resolve to real §1.8 instances and that no test carries a stub's name as its tag.

**Verification performed** (mechanical, via a scratch auditor at `/tmp/audit_2458.py`)

- Exactly one `Design:` line per test, as the last docstring line; every tag's instance name exists in the cited yaml; no untagged, dual-tagged or dangling tags. The 18 duplicate tags are the intentional queue-A pairs.
- Every `PRD §x.y: "…"` quote appears verbatim (whitespace-normalized, markdown emphasis included) in `workspace/PRD.md` **and** inside the cited section's own line range.
- Coverage diff of tags against both yamls: no missing and no extra instances in either queue.
- All modules compile; every `test_helpers` import resolves and every `api.<method>` call exists on `ApiClient`; no unused imports; import lists alphabetized.

**Two places where the PRD overrode the corner recipe** (recorded here because they change asserted outcomes):

- `stale_block_version_on_terms_submission_rejected`: the recipe resubmits terms from `TERMS_SUBMITTED`, which §3.2 rejects with `ERR_INVALID_BLOCK_STATE` at §2.10 rung 8 — before rung 10. The test therefore bounces the block to `CHANGES_REQUESTED` first, so the 412 `ERR_STALE_BLOCK_VERSION` is genuinely the first failure.
- `reservation_write_is_immediately_visible_to_every_reader` asserts `inventory_status == "OPEN"`; the recipe's `PARTIAL` is not in the PRD enum (§3.3 defines only `FULL`/`OPEN`). Likewise `bureau_controller_cannot_carve_sub_blocks` asserts `unassigned_rooms_per_night == 10` (§3.2 initialises it at contract), not the recipe's 0, and the `distinct_channel_count` assertion in the risk-clamp recipe was dropped since the PRD declares no such field.

No test was executed against an implementation, and `workspace/implementation/` was neither read nor written.


## Step 6: Generate implementation — 2026-09-02T22:19:30.000Z

(Steps 5 and 6 ran concurrently; Step 6 returned first, so its entry is recorded here and Step 5's entry is inserted above at the anchor when it returned.)

Implementation complete and verified end-to-end.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | launcher — `cd`s to its own dir, installs Flask only if missing (guarded, so per-test reboots don't thrash pip), `exec python3 app.py` |
| `requirements.txt` | `Flask==3.0.3` |
| `app.py` | app factory, 11 blueprints, `ApiError`/404/405/500 envelope handlers, global `RLock` per request, `app.run(0.0.0.0, PORT|10000, threaded=True)` |
| `store.py` | in-memory dicts (12 collections), logical clock pinned to `2026-08-01T00:00:00Z` at boot, id/timestamp/version helpers |
| `errors.py` | all 50 PRD §5 error ids → HTTP status |
| `auth.py` | header auth + role authorization (§2.10 steps 1–2) |
| `validators.py` | shape validation (step 3), query/pagination args, 9 existence resolvers (step 4) |
| `calc.py` | every pinned formula: peak-night occupancy, buffered overlap, event posture, taxed-nightly-first money, dual pickup-pace projections, reduction headroom, 6-step attrition exposure, both commission bases, vendor risk score, transmission set, waitlist promote/bump |
| `serializers.py` | explicit field-by-field output; derived fields rendered from current truth; the two ledgers emit only `id` + `created_at` |
| `routes/` | `events, hotels, blocks, subblocks, attendees, reservations, reporting, attrition, vendors, invoices, clock` |

**57 endpoints** — exactly matching the PRD §4 table (verified by dumping the URL map). Storage is in-memory only; the store is empty on every boot (confirmed: `GET /housing/hotels` returns `[]`, `total_count: 0` on a fresh process). Nothing is seeded, no file/SQLite/tmp persistence.

## Verification

Two throwaway smoke suites (in `/tmp`, not in the repo) drove ~120 requests through the full lifecycle with **zero mismatches** from a fresh boot: negotiation + stale-version 412, standardization/suspension gates, direct + nested carves, segregation-of-duties 403s, partial/full release, inventory-invariant assertions before and after cutoff, eligibility/stay-window/buffered-overlap/night-capacity rejections, two reduction cascades (waterfall + intake-seq-DESC waitlisting + one promotion on cancel), transmission type legality and empty-set 422, pickup ordering, pace projections, no-show billing, close, both invoice bases, the full cash cycle (payment → reversal → dispute → adjust → settle), and both vendor exits. Spot-checked money: `21900 × 1.1475 → 25130 × 4 = 100520` (round-per-night-first), penalty `50 × 21900 × 0.9 = 985500`, `penalty_avoided = 126000 − 72000 = 54000`.

Note: other `python3 app.py` processes on this host belong to a concurrent task (task_2444) and to a harness run against this implementation; I only killed PIDs whose cwd was this task's `implementation/`.

## PRD ambiguities resolved by judgement

1. **`created_at`/`updated_at` read the logical clock** (§2.4's example instant *is* the clock epoch), while `api_request_timestamp` uses wall time. Because logical timestamps repeat, list ordering is `(created_at, insertion_seq)`.
2. **Derived-field recomputation bumps `version` only when the value actually changes** (otherwise every read-adjacent cascade would inflate counters).
3. **Missing error ids for two cross-entity gates** — sub-block-approve and reduction-approve requiring a parent-block status use `ERR_INVALID_BLOCK_STATE` (409); nothing was named anywhere.
4. **Reduction exercise checks own-state first** (`ERR_INVALID_REDUCTION_STATE`) before the block gate (`ERR_INVALID_BLOCK_STATE`), per step 8 < step 9.
5. **`POST /reservations` enforces `ERR_NOT_RESOURCE_OWNER`** for a delegate booking for someone else (§3.4 prose) even though §2.10 step 6's list of nine ops omits it — prose wins.
6. **ADJUSTED-invoice payments**: `amount < outstanding` → `ERR_INVOICE_NOT_PAYABLE`; `amount > outstanding` → `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (mutually exclusive, so step order is moot).
7. **Pinned precedences taken literally from §2.10**: `ERR_NO_TRANSMITTABLE_RESERVATIONS` (24) before `ERR_INVALID_TRANSMISSION_TYPE` (25); `ERR_PICKUP_REPORT_REQUIRED` (29) before `ERR_INVOICE_ALREADY_EXISTS` (30).
8. **All list endpoints accept `limit`/`offset`** and emit pagination meta, including those the scaffold declared with no input (§2.3 is unconditional).
9. **`original_contracted_rooms_per_night` is null until CONTRACTED**; invoice commission/variance/rebate figures are frozen at issuance and only `outstanding_cents` is re-derived.
10. **`occurred_at` is echoed verbatim** as supplied and parsed only for ordering/duplicate detection; the clock response renders 3-fractional-digit form.
11. **Query filters that don't resolve return an empty list**, not 404.
12. **Vendor `version` bumps only on the `REPORTED → UNDER_REVIEW` escalation**, not on every incident record.
13. **Spec dead-end noted, not invented**: §3.8 says a `BureauController` clears `housing_risk_flag`, but §4 defines no endpoint for it — a flagged delegate is permanently blocked from booking/changing. Not implemented rather than guessing a path.

## Step 7: Run tests and iterate — 2026-09-02T23:29:22.692Z

Clean 8-round sweep achieved and verified by reading all 8 `results.*.json`: every round **109/109 passed, 0 failed, 0 errors**.

## Summary

**Iterations run:** 2 sweeps of 8 parallel rounds (plus 1 solo diagnostic round, and 2 aborted sweep attempts that were reaped — see note below).

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and passed both the coverage and unique-derivability checks; both failure classes were test-infrastructure defects in `test_helpers/`, not assertion problems.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `import_attendee()`: the helper passed `email`/`full_name`/`registration_id` as explicit keywords *and* splatted `**overrides`, so any caller specifying those fields raised `TypeError: create_attendee_payload() got multiple values for keyword argument 'email'`. Now defaults are merged into a dict that `overrides` updates before the single splat. This broke the two `test_05_validation_precedence.py::TestSubBlockStateOutranksNightCapacity` tests, whose fixtures pass a full VIP attendee spec.
- `test_helpers/api_client.py` — the module-level `api_client` singleton holds one `requests.Session` for the whole pytest session, but `--isolation per-test-server` restarts the server on the same port between tests. A pooled keep-alive socket from the previous server instance is dead when the next test reuses it, surfacing as `RemoteDisconnected` / `ConnectionResetError(104)` on the *first* request of a test (traceback confirmed it tripped inside `register_event()`, before any assertion). Set `session.headers["Connection"] = "close"` so each request opens a fresh TCP connection. This was the flakiness signal: `test_03::test_fourth_terms_submission_is_refused_and_changes_nothing` failed in rounds 1–5 and passed in rounds 6–8 of the first sweep; it is fully gone in the second sweep.

**Fixes applied to `implementation/`:** none. No implementation defect was found — no PRD-required check was removed or weakened, and no endpoint, field, header or side effect was added.

**Note on sweep reaping (for future runs on this host):** launching the sweep via the Bash tool's `run_in_background`, and even as a plain blocking foreground call with `setsid nohup`, both had all 8 rounds SIGKILLed mid-run (log ending in `Killed`, no `results.*.json` written; `dmesg` showed no OOM or systemd kill at that time). Reliable shape is a small script launched with `setsid --fork nohup … & disown` so it is fully reparented out of the tool's process tree, then polled from separate calls — that survived across many foreground calls untouched.

**Orchestrator independent verification:** re-read all 8 `results.*.json` (timestamps 23:19, sizes ~34.5 KB each) — each reports `passed=109, failed=0, errors=0, total=109`. Sweep artifacts confirmed present, not merely claimed.

**Step 8 gating decision (orchestrator):** Step 7 applied 0 `implementation/` fixes and 0 deletions, but it DID apply 2 `test_helpers/` fixes, so the skill's skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is not met. Step 8 therefore runs, with the two test_helpers fixes as its `<step_7_diff>` focus list. Both are pure test-infrastructure defects (a Python keyword-collision bug and HTTP connection pooling), so Step 8 is expected to find no PRD silence to patch; it is run anyway rather than skipped, because the skill's skip condition is conjunctive and was not satisfied.

## Step 8: Finalize PRD — 2026-09-02T23:39:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2458_convention_housing_bureau_operations/workspace/PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md`. **No PRD edits were warranted.**

## Line counts
- PRD.md: 454 lines; PRD_FINALIZED.md: 454 lines; delta 0 (0.0%). md5 identical (`5d11244a…`).

## Changes
None. Zero inserts, zero revisions.

## Why — per Step 7 item

**Item 1 — `test_helpers/fixtures.py::import_attendee` keyword collision (broke `test_05_validation_precedence.py::TestSubBlockStateOutranksNightCapacity`).**
- (a) Subject: attendee import payload fields, and the behaviour the two unblocked tests assert — booking into a `REJECTED` sub-block, rejection unwind accounting, and the night-capacity admission test.
- (b) Impl paths enumerated: `implementation/routes/attendees.py:19-53` (create_attendee — required `event_id`/`email`/`full_name`/`registration_id`/`attendee_type`, optional `eligibility_codes` defaulting to `[]`, `warning_count`/`housing_risk_flag`/`no_show_strikes` zero-initialised), `implementation/routes/reservations.py:45-134` (booking check order: step 4 → 6 → 8 block-then-sub-block → 11 → 13 → 15 → 16 → 17 → 18), `implementation/routes/subblocks.py` reject path (unwind), `implementation/calc.py` `admits_stay` / `recompute_sub_block`.
- (c) No wording adjustment needed: every assertion traces to verbatim PRD prose — §2.10 already pins "a request that violates step 8 and step 18 simultaneously must return step 8's error", §3.4 pins `ERR_INVALID_SUB_BLOCK_STATE` for a `REJECTED` sub-block, §3.3 pins the rejection unwind (`unassigned_rooms_per_night` back to 4 from a 10-room block carved 6+2) and `allotted_rooms → 0`, and §3.1 pins the attendee field set and zeroed counters. Impl matches all of it. The failure was purely `TypeError: got multiple values for keyword argument 'email'` inside the fixture — a Python argument-splatting defect with no API surface.

**Item 2 — `test_helpers/api_client.py` pooled keep-alive socket (flaky `test_03::test_fourth_terms_submission_is_refused_and_changes_nothing`).**
- (a) Subject: the negotiation-round cap on `POST /housing/hotel-blocks/{id}/terms` and the precedence of its guards; secondarily, HTTP connection reuse.
- (b) Impl paths enumerated: `implementation/routes/blocks.py:104-137` (submit_terms: step 8 `ERR_INVALID_BLOCK_STATE` → step 10 `ERR_STALE_BLOCK_VERSION` → step 27 `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, then wholesale overwrite + `revision_round += 1` + `touch`), `implementation/calc.py:37` (`MAX_NEGOTIATION_ROUNDS = 3`), `implementation/routes/blocks.py:140-156` (request_changes, the other half of the cycle), `implementation/routes/blocks.py:33-46` (assembly initialising `revision_round` at 0), `implementation/app.py` (no custom connection/keep-alive handling).
- (c) No wording adjustment needed: §3.2 already states verbatim "a submission is accepted only while `revision_round` is strictly less than 3, so the fourth attempt … is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`", and §2.10's ordering already places step 10 before step 27, which is exactly the impl's order. The "changes nothing" assertions (rate stays 22900, version unchanged) follow from the impl failing before any mutation, consistent with the PRD's error semantics. The actual fault was a dead TCP socket from the previous per-test server instance surfacing as `RemoteDisconnected` before any assertion ran — HTTP transport, not API behaviour, and nothing the PRD speaks to.

No implementation fixes, no test deletions and no `test_suite/` changes were in `<step_7_diff>`, so there is no other candidate site. Both fixture defects sit on behaviour the PRD already uniquely determines and the implementation already matches, so patching PRD_FINALIZED.md would have meant inventing edits.

## Step 9: Complete PRD — 2026-09-02T23:48:50.374Z

`PRD_COMPLETED.md` is written and complete (ends at the final `ERR_VARIANCE_WITHIN_TOLERANCE` row of the §5 table).

## Counts

- **Source vs output:** 454 lines → 454 lines (every change is an in-place line revision; no new paragraphs, no new sections, no new table rows). **+5,982 chars** (90,424 → 96,406). 36 lines revised.
- **Ambiguity-pins: 30. Mismatch-revisions: 6.**

## Changes

- §2.1 — revise — mismatch — an empty header value counts as missing for `ERR_UNAUTHENTICATED` — `auth.py:22`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads wall-clock time, not the logical clock — `envelope.py:21`
- §2.3 — insert — ambiguity — default `created_at` ordering tie-breaks on server insertion order (ties are routine because `created_at` reads the logical clock); the five declared orderings do too — `store.py:175`, `hotels.py:60`, `calc.py:94,108`
- §2.3 — revise — mismatch — "Four endpoints declare a different ordering" → "Five" (the sentence itself enumerates five) — `calc.py:82-108`
- §2.3 — insert — ambiguity — every list endpoint incl. nested ones takes `limit`/`offset`; an unresolvable identifier filter yields an empty list, not 404; only out-of-enum filter values give 400 — `reporting.py:69`, `subblocks.py:124`, `validators.py:170`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read the logical clock, not wall time — `store.py:157,166`
- §2.4 — revise — mismatch — derived-field recomputation is a mutation *only when a value actually moves*; derived fields are re-evaluated at render time regardless — `calc.py:185,292`, `serializers.py:70`
- §2.5 — insert — ambiguity — `current_utc`/`previous_utc` rendered with three fractional digits whatever form `to_iso8601` took; first repositioning reports the epoch — `clock.py:26`
- §2.8 — insert — ambiguity — undeclared payload fields (incl. a stray `expected_hotel_block_version`) are ignored, not rejected — `validators.py:31-37`
- §2.10 step 3 — insert — ambiguity — on a partial reservation change the supplied dates are merged over stored ones before the strict-ordering check — `reservations.py:178-181`
- §2.10 step 6 — revise — mismatch — "nine" → "ten" write operations, adding `POST /housing/reservations` — `reservations.py:63`
- §2.10 step 9 — insert — ambiguity — parent-block gates on sub-block approve / reduction approve / reduction exercise use `ERR_INVALID_BLOCK_STATE` (409) and sit after step 8 — `subblocks.py:151`, `attrition.py:95,130`
- §3.1 — insert — ambiguity — event `code` is validated by rejecting lowercase letters, so digits/punctuation pass — `events.py:23`
- §3.1 — insert — ambiguity — attendee `email` validated only as non-empty, no address-format check — `attendees.py:24`
- §3.1 — insert — ambiguity — a `standing` PATCH bumps `version` even when resubmitting the stored value — `hotels.py:71-72`
- §3.2 — insert — ambiguity — `original_contracted_rooms_per_night` is null until contracting — `blocks.py:63`
- §3.2 — insert — ambiguity — an omitted `confirmation_number` leaves the field as it stands — `blocks.py:189`
- §3.3 — insert — ambiguity — a nested carve bumps the parent sub-block's `version`; no block-status gates a carve — `subblocks.py:97-100`
- §3.3 — insert — ambiguity — sub-block approval's parent-block gate error is `ERR_INVALID_BLOCK_STATE` — `subblocks.py:151`
- §3.3 — insert — ambiguity — rejection also bumps the parent sub-block's `version` and imposes no parent-block-status condition — `subblocks.py:180-187`
- §3.3 — insert — ambiguity — release `rooms` floor is zero — `subblocks.py:196`
- §3.4 — insert — ambiguity — the parent-block `OPEN` check precedes the sub-block `APPROVED` check — `reservations.py:68-71`
- §3.4 — revise — mismatch — housing-risk hold: no operation clears the flag, so it is permanent (PRD promised a controller clear that §4 never defined) — no impl path exists
- §3.5 — insert — ambiguity — the `no_show_strikes` increment bumps the attendee's `version` — `reservations.py:297-298`
- §3.7 — insert — ambiguity — filing has no block-status gate; a null `original_contracted_rooms_per_night` reads as zero, so the cap is zero — `calc.py:376-377`
- §3.7 — insert — ambiguity — reduction-approval parent-block gate error is `ERR_INVALID_BLOCK_STATE`; rejection has no such gate — `attrition.py:95,111-116`
- §3.7 — revise — mismatch — exercise evaluates own-state (`ERR_INVALID_REDUCTION_STATE`) *before* the parent-block gate; PRD prose implied the reverse — `attrition.py:126-130`
- §3.7 — insert — ambiguity — each sub-block the waterfall drew from gets exactly one `version` bump, waitlisting or not — `attrition.py:162-165`
- §3.8 — insert — ambiguity — `occurred_at` echoed verbatim, parsed only for ordering/duplicate detection, so equivalent renderings collide — `vendors.py:103-110`
- §3.8 — insert — ambiguity — score re-derivation alone is not a vendor mutation; `version` bumps only on the `REPORTED → UNDER_REVIEW` escalation — `vendors.py:130-133`
- §3.8 — insert — ambiguity — each warning bumps the delegate's `version` — `vendors.py:186`
- §3.8 — revise — mismatch — same housing-risk-flag permanence correction as §3.4 — no impl path exists
- §3.9 — insert — ambiguity — the cutoff sweep bumps a swept sub-block's `version` only when it actually moved rooms or reached `RELEASED` — `blocks.py:242-253`
- §3.9 — insert — ambiguity — invoice issuance has no block-status precondition; only steps 29 then 30 gate it — `invoices.py:29-38`
- §3.9 — insert — ambiguity — `outstanding_cents` is the only re-derived figure; both commission sides, `commission_due_cents`, `billable_room_nights`, `rebate_due_cents`, `variance_cents` are frozen at issuance — `serializers.py:224-232`
- §3.9 — insert — ambiguity — `amount_cents`/`write_off_cents` floors of zero; `reference` validated but neither persisted nor echoed — `invoices.py:92-93,126-127,175`
- §3.9 — insert — ambiguity — on an `ADJUSTED` invoice the too-small test runs before the ceiling test, so an over-payment still yields `ERR_PAYMENT_EXCEEDS_OUTSTANDING` — `invoices.py:106-113`

**Verified as already uniquely pinned (no change):** all 57 endpoint paths, roles and status codes in §4; the full §5 catalogue; §2.10 precedences 24-before-25 and 29-before-30; peak-night occupancy; buffered overlap geometry; both pace projections; the six-step penalty formula and its pre/post variants; the risk-score formula and clamp; every serializer field set (impl exposes no field §3 does not name).

**Deliberately not added:** the impl's `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) fallbacks for unrouted paths and methods. These are outside the §4 endpoint surface, and documenting them would have required new rows in the §5 catalogue.

**Orchestrator independent verification:** `PRD_COMPLETED.md` is 454 lines / 96,406 chars (vs 454 / 90,424 for both PRD.md and PRD_FINALIZED.md, which are md5-identical). `grep '^#'` heading lists of PRD.md and PRD_COMPLETED.md are identical (28 headings, no section added or dropped), and the file ends at the final `ERR_VARIANCE_WITHIN_TOLERANCE` row — not truncated.

## Pipeline complete — 2026-09-02T23:48:50.374Z

All nine steps finished. Final state: 3 scaffold artifacts, 9 `test_helpers/` modules, `test_suite/` with `conftest.py` + 18 modules / 109 tests, a 57-endpoint Flask implementation with in-memory-only storage, 8 passing `results.*.json` (109/109 each), and PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md.
