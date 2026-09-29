# Worklog — task_2505_regional_airline_capacity_purchase_agreement

## Step 1: Create task directory — 2026-09-03T02:45:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2505_regional_airline_capacity_purchase_agreement` and its `workspace/` subdirectory. Index 2505 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate scaffold — 2026-09-03T05:44:00.000Z

All three artifacts are written and pass the linter.

**Task 2505 — Regional Airline Capacity Purchase Agreement**
Directory: `/home/ubuntu/github/CodingPRD/tasks/task_2505_regional_airline_capacity_purchase_agreement/`

**`SCAFFOLD.yaml`** (2429 lines, §1.0–§1.7; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- 12 entities (Agreement, CrewBase, Aircraft, Pilot, ScheduleCycle, FlightLeg, CancellationClaim, PassThroughClaim, Scorecard, Invoice, BrandAudit, ExtensionNegotiation), all with `common_fields: true`
- 12 state machines, 2 §1.2.1 concurrency rules (OCC on Agreement and ScheduleCycle), 9 calculations, 32 ordered validations, 62 endpoints (24 GET / 38 POST, prefix `/cpa`), 45 errors, 5 roles
- Complexity profile: Ledger reconciliation × Multi-party negotiation; flat topology; cyclic state machines; `role_model: segregation_of_duties`; `consistency_model: immediate`; layers = dual-variant calculation, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (1852 lines) — 9 rule blocks, 19 instances: dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (2), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2)

**`SCAFFOLD_CORNER_DESIGN.yaml`** (3144 lines) — 83 instances across all 9 taxonomy sections: 56 full `test_recipe` instances + 27 `excluded_because` stubs deferring to named §1.8 instances. Per section: entities 11, state_machines 17 (11/6), calculations 14 (6/8), validations 13 (8/5), endpoints 4, errors 10 (6/4), rbac 7, cross_cutting_complexity_layers 6 (2/4), consistency_model 1

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint`; 853 calls scanned across §1.8+§1.9, all conform to §1.5, and every §1.1 FK has reverse-reachability
- Zero duplicate instance names across the union of both design files; every stub's cited `difficulty_instance` resolves to a real §1.8 instance; no stub carries a `test_recipe`
- All three files parse under `yaml.safe_load`; each design file has exactly one top-level key

Notable design points worth knowing downstream: invoice components are frozen at creation and never recomputed (so a post-issue scorecard recompute cannot change an issued total); the departure ledger is a conserved quantity (`metric_completed_departures + cancellations == published_departures`) exercised by both compensating-invariant instances; the pass-through admin-fee tier is pinned to the Step-2 base so later reconciliations cannot re-tier it; and Scorecard PUBLISHED→STALE auto-voids DRAFT/ISSUED invoices, which is why the ERR_SCORECARD_STALE recipe stales the scorecard *before* creating the FINAL invoice.

**Orchestrator note:** the Step 2 subagent's first turn was killed by an API timeout before writing any file. Rather than respawning a fresh agent (which would have re-derived the design from scratch), the orchestrator resumed the same agent via SendMessage with instructions to write the three files incrementally. It completed successfully on resume.

## Step 3: Copy shared files — 2026-09-03T05:45:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T06:03:00.000Z

PRD complete and verified.

## Deliverable

`workspace/PRD.md` — **449 lines**, written incrementally (1 Write + 7 Edits via a `<!-- CONT -->` sentinel anchor). Tail re-read and confirmed: the file ends at a complete `## 5. Error Code Catalogue` table row (`ERR_EXTENSION_TERM_NOT_LATER` | 422 Unprocessable Entity), no audit footer, no trailing sentinel.

## Section list

- **§1 Introduction** (3 paragraphs: CPA commercial context, spreadsheet pain, `/cpa` mount + logical clock)
- **§2 Global Specifications** — 12 subsections: 2.1 Acting Parties and RBAC · 2.2 API Response Structure (verbatim block, byte-identical, machine-verified) · 2.3 Pagination and List Ordering · 2.4 Common Resource Properties and Version Semantics · 2.5 The Logical Clock and Contract Expiry · 2.6 Money, Block Hours and Rounding Discipline · 2.7 Derived Fields and Cascade Propagation · 2.8 Ledger Conservation · 2.9 Stale-Version Guards · 2.10 Resource Addressing and Reference Resolution · 2.11 Segregation of Duties · 2.12 Rejection Precedence (18-item ordered chain + 3 worked precedence examples)
- **§3 Business Logic & Workflows** — 9 subsections: 3.1 Standing Up the CPA · 3.2 Crew Bases, Hiring Pipeline and Staffing Arithmetic · 3.3 Fleet Registration, Induction, Grounding, Renewal · 3.4 The Settlement Month: Cycles and Flight Legs · 3.5 Adjudicating Cancellation Controllability · 3.6 Pass-Through Categories and Reconciliation · 3.7 Performance Scoring, Brand Standards, Incentive Outcome · 3.8 Invoicing, Settlement and Compensating Reversals · 3.9 Renegotiating the Term
- **§4 Endpoint Definitions** — status-code paragraph + 4-column table (Method | Path | Description | Authorized Role(s))
- **§5 Error Code Catalogue** — 2-column table (Error ID | HTTP Status Code)

## Coverage confirmation (machine-verified against SCAFFOLD.yaml)

- **Endpoints: 62/62.** Set-difference against `endpoints[]` on (method, path) is empty in both directions; no duplicates. Role column verified endpoint-by-endpoint against `roles` (`Any` expands to all five roles) — 0 mismatches. The ten 201 creators in the scaffold match the ten named in the §4 status paragraph.
- **Errors: 45/45**, each in backticks in prose and once in the §5 table; 45 unique rows.
- **Entities: 12/12**; all 12 state machines, 54 transitions, 2 concurrency rules, 9 calculations, 32 validations, 5 roles reflected.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Pass A: all `entities[].fields[].name` across all 12 entities appear verbatim in backticks — 0 missing. Pass B: every identifier in every `request_body` / `input` / `query_params` / `path_params` across all 62 endpoints appears verbatim in backticks (optional markers stripped) — 0 missing. Pass C (extra): every state name in every state machine and every field `enum` value appears in the prose — 0 missing. (The extraction was made fence-aware after an initial run mis-paired backticks across the §2.2 ```json fences and produced spurious misses.)

**Contract 2 — Rule Coverage: PASS.** All 32 validations are stated with their error ids and their relative ordering (§2.12 chain, priorities 1→80, including the alternation groups at priorities 3, 12 and 58). Both OCC rules are documented with their `occ_field`, non-optionality, 412 code and *why* the guard exists (offer supersession; invoice supersession). All 54 transitions are described with from/to co-located in a single paragraph (the four BrandAudit rows are expressed as the two `finding_status` / `remediation_status` dimension chains rather than as `field=VALUE` literals). All 9 calculations pass the reconstruction test, including the pinned per-leg-then-sum rounding order, the completion-factor numerator/denominator asymmetry, the forfeiture branch, the nested incentive cap chain, the step-2-not-step-5 admin-fee tier pin, and the dual headcount/pipeline staffing bases. A numeric-constant sweep found every scaffold constant present. Cross-entity cascades (termination stand-down, attrition→grounding, staleness→invoice void→money unwind), `applies_to` scopes, field-level defaults and sibling-branch symmetry are all covered.

**Contract 3 — §3 Path Purity: PASS.** 267 unique backtick tokens in §3; automated scan found 0 tokens starting with `/`, 0 bare HTTP methods, and 0 method+path combinations.

## Scaffold contradictions resolved (documented in the PRD, §1.1/§1.2 tables preferred over §1.5 prose)

Termination cascade withdraws only `PENDING_INDUCTION` tails (no `IN_SERVICE`/`GROUNDED_STAFFING` → `WITHDRAWN` transition exists); attrition cascade uses `grounded_reason` `STAFFING_SHORTFALL` (the only enum member, not `PILOT_SHORTFALL`); a new cycle's `metric_completed_departures` and `departure_ledger_total` open at `published_departures` (required by the derived formulas plus the stated conservation invariant) and `passthrough_settlement_usd` at 0.00; invoice supersession is scoped to same cycle *and* same `variant`; `incentive_pool_cap_usd` / `penalty_cap_usd` documented as the "at least zero" exception to the money-positive rule; `ERR_ALREADY_TERMINAL` scoped to the seven entities whose machines have terminal states, `ERR_INVALID_STATE` elsewhere; brand-audit staleness asymmetry (creation and finding closure stale scorecards; remediation verification does not).

**Orchestrator anti-truncation check:** PRD.md tail independently verified by the orchestrator — file ends at a complete §5 table row; §5 contains exactly 45 `ERR_` rows and §4 exactly 62 GET/POST rows, matching the scaffold counts. No truncation; no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T06:40:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the skill's physical-isolation requirement. Step 6 returned first; its summary is recorded here, Step 5's below.)

All 13 route modules are in place, the app imports cleanly, and the server boots and answers over HTTP.

## Files written

`workspace/implementation/`

- Launcher/deps: `start.sh` (exec `python3 app.py`, `PORT` env, pip-installs Flask only if missing), `requirements.txt`
- Foundation: `core.py` (logical clock pinned to `2026-08-01T00:00:00Z` per boot, Decimal helpers), `errors.py` (44-entry catalogue), `db.py` (12 in-memory dicts, `new_entity`/`touch` with per-request version dedup), `response.py` (envelope + pagination), `auth.py`, `validate.py`, `lookup.py`, `enums.py`, `calc.py` (9 calculations + all pinned constants), `derive.py` (staffing/grounding loop, cycle ledger, agreement counters, scorecard staleness, invoice void cascade)
- Routes (`routes/`): `__init__.py`, `common.py`, `clock.py`, `agreements.py`, `negotiations.py`, `crew_bases.py`, `aircraft.py`, `pilots.py`, `schedule_cycles.py`, `flight_legs.py`, `cancellation_claims.py`, `passthrough.py`, `scorecards.py`, `invoices.py`, `brand_audits.py`

Storage is in-memory only (no file, no /tmp, no SQLite) and nothing is seeded — `create_app()` calls `clock.reset()` + `store.reset()` and registers routes, nothing else.

## Endpoint count

Exactly **62** `GET`/`POST` rules under `/cpa`, matching the PRD §4 table one-for-one (clock 1, agreements 6, extension-negotiations 6, crew-bases 3, aircraft 6, pilots 5, schedule-cycles 6, flight-legs 6, cancellation-claims 5, pass-through-claims 5, scorecards 3, invoices 4, brand-audits 6).

## Boot verification

`PORT=18432 bash start.sh` (and a second fresh boot on 18433 after the final edits) came up in ~2s; `GET /cpa/agreements` returned a well-formed array envelope (`meta.limit/offset/total_count/has_more`, `response_type: "array"`, `data: []`) and `POST /cpa/agreements` returned 201 with bare-UUID `id`, `version: 1` and 2dp money. Both processes were killed afterwards; ports confirmed closed.

## Behavioural spot-checks (in-process client, full happy path + traps)

Ledger `departure_ledger_total ≡ published_departures` held across cancel and uncontrollable finalization (3 → 3 with counters moving 1/0 → 0/1); `ERR_AIRCRAFT_TURN_CONFLICT` at a 20-minute turn and acceptance at 35; `ERR_CLAIM_ALREADY_FINALIZED` on reinstate; airport-fee allowance 44,000.00 from a 40,000.00 estimate / 47,000.00 actual with settlement 45,320.00 (3% tier chosen from the base total); scorecard 100.00/100.00/5.00 → 5 points → gross 60,000.00 with incentive floored to the 5% revenue-share ceiling 27,388.00; FINAL invoice total 620,468.00; `ERR_STALE_CYCLE_VERSION` on a bad `expected_schedule_cycle_version`; raising a CRITICAL/4-finding audit staled the scorecard, voided the ISSUED invoice with `AUTO_SCORECARD_STALE`, reverted the cycle `SETTLED → CLOSED` and returned `settled_to_date_usd` to exactly 0.00; recompute republished with `brand_penalty_usd` capped at 25,000.00; negotiation counter→accept rewrote the agreement term/rate; clock advance swept the agreement to `EXPIRED`; pagination, enum-filter, path-404 and auth guards all returned the right error ids.

One caution for the worklog: during teardown I used `pkill -f "python3 app.py"`, which on this shared host could have killed a transient server belonging to the concurrent test-suite agent's runner (the runner relaunches per test, so any effect would be a one-off failure at ~06:36 rather than lasting damage). No `app.py` process of mine is running now.

**Orchestrator note on that caution:** the Step 6 agent's `pkill -f "python3 app.py"` is broad enough to have hit servers belonging to other concurrent pipelines on this host, not just its own. Nothing can be undone now; the practical consequence is that any single-round test failure timed near 06:36 in *this or a neighbouring* pipeline should be treated as collateral, not a defect. Step 7's 8-round sweep runs well after that window, so it is unaffected.

## Step 5: Generate unit tests — 2026-09-03T07:20:00.000Z

(Recorded after Step 6 because Step 5, launched concurrently with it in the same orchestrator message, finished later.)

Queue B is complete; the whole suite is now on disk and verified.

## Files written this session
- `test_suite/test_16_role_access_and_duties.py` — 7 tests (`Corner/rbac/*`)
- `test_suite/test_17_concurrency_guards.py` — 2 tests (`Corner/cross_cutting_complexity_layers/*`)
- `test_suite/test_18_immediate_consistency.py` — 1 test (`Corner/consistency_model/*`)

## Final suite state
`test_helpers/` (Stage 1, 7 modules + `conftest.py`) and `test_suite/` with 18 files, **94 tests, 75 distinct `Design:` tags**:
- **Queue A (§1.8 difficulty)** — `test_01`…`test_09`, 38 tests covering all **19/19** non-stub difficulty instances (the paired instances — epsilon pairs, dual-variant pairs, priority pairs — each get two single-tagged tests, as established earlier in the run).
- **Queue B (§1.9 corner)** — `test_10`…`test_18`, 56 tests covering **56/56** non-stub corner instances exactly once: entities 11, state_machines 11, calculations 6, validations 8, endpoints 4, errors 6, rbac 7, cross_cutting 2, consistency_model 1. None of the yaml's 27 `excluded_because` stubs was translated.

## Verification
- `python /tmp/verify_2505.py` over the whole `test_suite/`: **PROBLEMS: 0** — every `PRD X.Y: "…"` quote is a verbatim, correctly-sectioned substring of `workspace/PRD.md`; tests == tags; every tag resolves to a real instance name; exactly one `Design:` line at the end of each test docstring; all `test_helpers` imports and `api.*` methods resolve; no file mentions the design source.
- `python -m pyflakes test_suite/*.py test_helpers/*.py`: clean.
- `python -m pytest test_suite --collect-only -q`: **94 tests collected**, no import errors.

## Instances skipped or adjudicated (PRD-first filter)
No instance was skipped outright; three recipes were restructured earlier in the run where the yaml over-asserted beyond the PRD, and the rbac/cross-cutting/consistency recipes needed none:
1. Error-envelope `data == null` sub-assertions dropped (contradict §2.2, which defines error `data` as `{error_id, message}`).
2. Clock-expiry recipe reordered so the PLANNED cycle exists before expiry and is then refused `open` (§2.5's own sentence), rather than asserting a *creation* refusal §2.12 item 7 does not support.
3. Provisional invoice raised while the month is OPEN, then closed, since the PRD neither permits nor forbids raising one against a CLOSED month.

New this session, `brand_auditor_cannot_acknowledge_its_own_finding` was confirmed uniquely derivable: from `OPEN` the `ACKNOWLEDGED → CLOSED` transition is undeclared, so §2.12 item 9 (`ERR_INVALID_STATE`) outranks item 16 (`ERR_REMEDIATION_NOT_VERIFIED`) — asserted as the yaml specifies.

`workspace/implementation/` was never read or modified.

## Step 7: Run tests and iterate — 2026-09-03T08:00:00.000Z

All 8 rounds of the second sweep are fully green: 94/94 in every round. The final passing `results.{1..8}.json` are left in `workspace/implementation/`.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, 94 tests, per-test-server isolation).

**Sweep 1 failures (union across 8 rounds):** 3 distinct tests
- `test_the_newest_tail_is_the_one_grounded_and_stays_allocated` — 8/8 rounds
- `test_training_credit_floors_to_zero_and_only_qualification_restores_the_tail` — 8/8 rounds
- `test_three_legs_of_one_month_paginate_two_then_one` — 5/8 rounds (the flakiness signal)

All three traced to the same root cause: the service reads a **logical clock that only an administrator advances**, so every record a test creates shares an identical `created_at`. The PRD's tie-break clauses are therefore the rules that actually decide ordering, and all three tests had encoded creation order instead.

**Tests deleted:** none. Every failing test passed STEP 1a (PRD verbatim-covers) and STEP 1b (uniquely derivable — the PRD states both orderings and their tie-breaks as full sentences).

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added three PRD-order helpers (and exported them): `default_list_order` (PRD 2.3: `created_at` asc, `id` asc tie-break), `grounding_candidate_order` (PRD 3.3: `created_at` desc, `tail_number` asc tie-break), `restoration_candidate_order` (PRD 3.3: `created_at` asc, `tail_number` asc). These let a test express the PRD selector instead of hardcoding an index that only holds when timestamps differ.

**Fixes applied to `test_suite/` (STEP 2 — test bugs, assertions mis-translated PRD):**
- `test_suite/test_10_entity_shapes_and_references.py::TestFlightLegListing` — asserted the paginated pages equalled *creation* order; PRD 2.3 mandates `id` ascending as the tie-break when records share a creation timestamp, which all three legs do. Now compares against `default_list_order([...])`, and the docstring quotes the ordering sentence. This was the flaky one: it passed only when the three random UUIDs happened to sort into creation order.
- `test_suite/test_04_transitive_cascades.py` — asserted the *later-registered* tail was grounded; with tied `created_at`, PRD 3.3's `tail_number`-ascending tie-break selects `N701RG`, not `N702RG`. Now selects the victim via `grounding_candidate_order` and quotes the selector sentence; test renamed `test_the_first_ranked_tail_is_the_one_grounded_and_stays_allocated`.
- `test_suite/test_11_state_machine_transitions.py::TestGroundedTailRestorationIsConditional` — same defect (`aircraft_ids[1]` hardcoded as the grounded tail); now derives grounded/retained tails from `grounding_candidate_order`.

**Fixes applied to `implementation/`:** none. `derive.py::_ground_or_restore` and `db.py::ordered` were already faithful to PRD 3.3 and 2.3 respectively — the implementation was correct in all three cases and no PRD-required check was weakened or removed.

**Orchestrator verification of the sweep artifacts:** the orchestrator independently parsed all eight `workspace/implementation/results.{1..8}.json` (all written 07:46) and confirms `passed == total == 94` in every one; `test_suite/` still holds 18 files / 94 tests, consistent with the reported zero deletions.

**Step 8 skip decision:** Step 8 is NOT skipped. Step 7 needed a second sweep and applied 1 `test_helpers/` fix plus 3 `test_suite/` fixes, so the skip condition (zero deletions AND zero test fixes AND zero implementation fixes) is not met. Note that with 0 `implementation/` fixes the expected Step 8 diff is small — the ordering tie-breaks the fixes turned on were already stated in PRD 2.3 / 3.3, which is precisely why the implementation needed no change — so a near-empty PRD_FINALIZED.md is a legitimate outcome here rather than a sign Step 8 failed.

## Step 8: Finalize PRD — 2026-09-03T08:05:00.000Z

`PRD_FINALIZED.md` written. Near-zero diff, as the Step 7 note anticipated.

## Line counts
- `PRD.md`: 449 lines; `PRD_FINALIZED.md`: 449 lines — 0.00% line delta; 2 of 449 lines revised (0.45% of lines touched), 2 clauses inserted, nothing removed.

## Changes
- **§3.3 (grounding selector)** — revise — appended `id` ascending as the final tie-break after `created_at` desc / `tail_number` asc — `implementation/derive.py:30-31`
- **§3.3 (restoration selector)** — revise — appended `id` ascending as the final tie-break after `created_at` asc / `tail_number` asc — `implementation/derive.py:42-43`

Rationale: the impl's sort keys are `(created_at DESC, tail_number ASC, id ASC)` and `(created_at ASC, tail_number ASC, id ASC)`; PRD 3.3 stated only the first two components, so the third was a real impl-pinned choice at exactly the Step 7 site. It is reachable: `routes/aircraft.py:43-46` scopes `tail_number` uniqueness to `agreement_id` only and never requires `assigned_base_id`'s base to belong to that agreement, so one base can hold two same-named tails, and `calc.py:276-281` counts tails at a base regardless of agreement, so both can be `IN_SERVICE` candidates.

## Per-edit pre-edit search log

**Edit 1 — grounding selector**
- (a) Subject: the ordering/selection of tails for automatic grounding.
- (b) Enumerated: `derive.py::_ground_or_restore` (grounding branch, lines 27-35) — the sole selector; its only caller `derive.py::apply_base_staffing`; every callsite of that, found by grep: `routes/pilots.py` (advance, attrite), `routes/aircraft.py:101` (induct), `routes/aircraft.py:128` (transition), plus the base-closing path in `routes/agreements.py` (checked — closes bases, withdraws `PENDING_INDUCTION` tails, does not re-select `IN_SERVICE` tails). Also grepped all of `implementation/` for `tail_number` and for `sort`/`ordered` to confirm no parallel tail-ordering exists (`calc.py:276` counts without ordering; `db.py::ordered` is the generic `created_at,id` list order). Confirmed the impl's Python two-pass stable sort yields exactly `created_at DESC, tail_number ASC, id ASC`.
- (c) Adjustment: worded the addition as conditional ("should two candidates share both") rather than restating the whole key, so the sentence adds a level without re-asserting or reordering the two levels PRD already pinned.

**Edit 2 — restoration selector**
- (a) Subject: the ordering/selection of grounded tails returned to service.
- (b) Enumerated: `derive.py::_ground_or_restore` restoration branch (lines 37-47) — the sole selector and the sole writer of `GROUNDED_STAFFING → IN_SERVICE`; grepped `GROUNDED_STAFFING` across `implementation/` to confirm no other restoration path (other hits are read-only: `calc.py` fleet-paid statuses / `ownership_aircraft_count`, `routes/aircraft.py:116` transition source states, `routes/flight_legs.py` availability guards — none reorder or restore tails). Same caller set as Edit 1.
- (c) Adjustment: none beyond matching the same conditional, additive phrasing; kept "again with `tail_number` ascending as the tie-break" verbatim so the restoration/grounding symmetry the PRD draws is unchanged.

## Verification of the three Step 7 sites (no edit needed)
- `test_..._paginate_two_then_one` → `db.py:73-79` `sort_key = (created_at, id)`, applied in `routes/common.py:31` before filtering, then `response.py:97-105` windows the filtered set with `total_count` = pre-pagination filtered size and `has_more = offset+len < total`. Identical to PRD 2.3 as already written; PRD 2.5/§1 already pin that `created_at` comes from the admin-advanced logical clock, which is what makes the `id` tie-break decisive. Verbatim kept.
- `test_the_first_ranked_tail_is_the_one_grounded...` → grounding order faithful to PRD 3.3; only the `id` level was unstated (Edit 1). Grounding count `assigned - allocatable` and `grounded_reason = STAFFING_SHORTFALL` match PRD verbatim.
- `test_training_credit_floors_to_zero...` → `calc.py::pilot_staffing_shortfall` floors `in_training × 0.65` and computes `allocatable = min(cap, floor(pipeline_available / ratio))` exactly as PRD 3.2 states; restoration count `allocatable − len(IN_SERVICE)` matches PRD 3.3 verbatim. Only the `id` level was unstated (Edit 2).

No implementation change was needed or made, and no other PRD section was touched.

## Step 9: Complete PRD — 2026-09-03T08:35:00.000Z

**Orchestrator design decision.** Step 9 was run as THREE SEQUENTIAL file-partitioned passes over a single `PRD_COMPLETED.md`, rather than as one whole-implementation scan. Prior experience on this pipeline is that a single agent asked to "walk implementation/ exhaustively" across 12 entities / 62 endpoints skims instead of scanning and returns a PRD_COMPLETED.md byte-identical to its input — which is indistinguishable from a genuinely complete PRD but is actually a scan that never happened. Partitioning by implementation file forces each pass to read its slice. The passes had to be sequential (not concurrent) because all three edit the same output file. Partition: pass A = cross-cutting layer (app/core/db/response/auth/validate/lookup/enums/errors/routes-common/routes-clock); pass B = money layer (calc/derive/schedule_cycles/scorecards/invoices/passthrough); pass C = entity-lifecycle layer (the eight remaining resource route modules). Pass A created the file from PRD_FINALIZED.md; B and C edited in place.

**Aggregate result: 50 edits — 41 ambiguity-pins, 9 mismatch-revisions.** `PRD_FINALIZED.md` 449 lines / 91,700 chars → `PRD_COMPLETED.md` 453 lines / 110,475 chars (+18,775 chars, +20.5%; 46 diff hunks). Nearly all edits are in-paragraph, as required; no new sections.

### Pass A — cross-cutting layer (18 edits: 14 ambiguity, 4 mismatch)

Confirmed `PRD_COMPLETED.md` created by `cp` from `PRD_FINALIZED.md`. 449 → 453 lines / 98,963 chars, 16 diff hunks.

- §2.1 — revise — ambiguity — a present-but-blank/whitespace header counts as absent; role match is exact and case-sensitive so a mis-cased role is `ERR_UNAUTHENTICATED`, never `ERR_FORBIDDEN_ROLE`; `X-User-ID` has no format check — `auth.py:30-35`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — `response.py:11,20`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, so it is constant between clock advances — `response.py:23-27`
- §2.2 — revise — ambiguity — non-list `meta` carries only the two request keys (no pagination keys) — `response.py:30-36`
- §2.3 — revise — ambiguity — out-of-range `limit` refused, never clamped; negative `offset` rejected; both must be base-10 integer literals; `offset` past the end returns empty `data` with full `total_count` and `has_more` false — `response.py:66-99`
- §2.3 — insert — ambiguity — filters: exact string equality, AND-combined, enum-typed filters validated against the vocabulary, FK-typed filters unvalidated (empty page not 404), undeclared query params ignored — `routes/common.py:12-27`
- §2.4 — revise — ambiguity — `id` is a random version-4 UUID, canonical lower-case hyphenated, never client-supplied — `core.py:43-44`
- §2.4 — revise — ambiguity — `updated_at` is byte-identical to `created_at` on a fresh resource — `db.py:41-50`
- §2.4 — insert — ambiguity — exactly one `version` bump per request even when two cascade hops touch the same resource; internal bookkeeping state is never serialised — `db.py:53-70`, `db.py:86-89`
- §2.5 — revise — ambiguity — `api_request_timestamp` added to the list of clock-sourced timestamps — `response.py:26`
- §2.5 — insert — **mismatch** — `to_iso8601` accepted grammar (optional fraction, `Z` or offset normalised to UTC, zoneless read as UTC; bare date/non-string/impossible date → `ERR_INVALID_REQUEST`); **no monotonicity is enforced, so the clock may be set backwards or to the same instant** (PRD said "drives it forward"); sub-ms input truncated, not rounded — `core.py:21-22,37-40,47-81`
- §2.6 — insert — ambiguity — strict input typing: money/hours/int must be JSON numbers (numeric strings and booleans rejected), int fields reject `3.0`, enums case-sensitive, `YYYY-MM-DD`/`YYYY-MM` strict; money and hours emitted as bare JSON numbers so a trailing zero may be elided — `validate.py:52-98`, `app.py:20-29`
- §2.10 — revise — ambiguity — path ids compared by exact string equality (unminted UUID and non-UUID are both just misses); trailing slash immaterial — `lookup.py:22-27`, `app.py:35`
- §2.10 — insert — **mismatch** — a body reference is structurally checked first (missing/null/non-string/blank → `ERR_INVALID_REQUEST`, not `ERR_REFERENCE_NOT_FOUND`), then resolved; all references resolved, in §3 declaration order, before any remaining field is validated — `validate.py:33-39`, `lookup.py:78-86`
- §2.12 item 5 — revise — ambiguity — `offset` >= 0 added; absent/empty/unparseable body read as `{}` (bodyless action endpoints succeed) while a non-object JSON body is `ERR_INVALID_REQUEST`; explicit `null` treated exactly as omission; undeclared body members ignored; required strings non-blank after trimming but stored verbatim — `validate.py:12-39`
- §2.12 items 9–10 — revise — **mismatch** — order swapped: the already-terminal guard is evaluated **before** the transition-declared check — `routes/common.py:36-46`, confirmed at every call site
- §3.1 — revise — **mismatch** — the terminal guard runs ahead of the state check, so a terminal target always reports `ERR_ALREADY_TERMINAL`; an action on an already `EXPIRED`/`TERMINATED` agreement reports `ERR_INVALID_STATE` (agreements are out of the guard's scope) — `routes/common.py:36-41`, `routes/agreements.py:73,92`
- §4 intro — insert — ambiguity — an unrouted path is a 404 with generic `ERR_NOT_FOUND` and no authentication check; a declared path with an undeclared method is a 405 with `ERR_INVALID_REQUEST`; neither is a §5 contract error — `app.py:50-57`

Verified already-pinned in pass A's slice: envelope shape/key order and `response_type` values; error `data` = `{error_id, message}`; `total_count` = filtered size before pagination and `has_more` semantics; default `limit` 10 / min 1 / max 100 / default `offset` 0; list ordering `created_at` asc then `id` asc; the four system properties, `version` starting at 1 and incrementing by 1, ISO-8601 with exactly three fractional digits; clock initial instant `2026-08-01T00:00:00Z` and reset-on-boot; the clock sweep's scope, ordering and role restriction; round-half-up, 2 dp money / 3 dp hours, the two caps as the `allow_zero` exception, floor = truncation; precedence 1→2 and 3→4/5; per-collection 404 mapping and `ERR_REFERENCE_NOT_FOUND`; both OCC fields' mechanics and placement; all 44 `error_id`→status pairs; all 24 enum vocabularies and seven terminal-state sets; 201-for-creation and all-roles GET access.

### Pass B — money/settlement layer (10 edits: 8 ambiguity, 2 mismatch)

453 lines / 98,963 → 102,720 chars; all edits in-paragraph.

- §3.8 ¶1 — revise — **mismatch** — impl imposes **no** cycle-status precondition on `PROVISIONAL` (the guard sits inside `if variant == "FINAL"`), and `FINAL` requires exactly `CLOSED` (so `SETTLED` is also refused) — `routes/schedule_cycles.py:147-155`
- §3.8 ¶2 — insert — ambiguity — creation never consults scorecard staleness (a `FINAL` invoice may be raised against a `STALE` scorecard, copying its current figures); supersession is same-variant + `DRAFT` only; the agreement's `version` increments by exactly 1 even where `open_invoice_count` nets back — `routes/schedule_cycles.py:158-168,188`, `derive.py:156-162,237-248`
- §3.8 ¶6 — insert — **mismatch** — the four issuance conditions are evaluated in the order written, locally overriding §2.12's generic placement of `ERR_INVALID_STATE`: the variant test precedes the month-`CLOSED` test, so a `PROVISIONAL` draft on a non-`CLOSED` month reports `ERR_INVOICE_VARIANT_NOT_FINAL`; also named `ERR_INVALID_STATE` for the month-status refusal — `routes/invoices.py:50-54`
- §3.8 ¶7 — insert — ambiguity — `SETTLED → CLOSED` reversion is conditioned on the month actually standing in `SETTLED` at void time; the void does not clear `issued_final_at`, and only `status`/`void_reason` are rewritten — `derive.py:237-243`
- §3.8 ¶5 — insert — ambiguity — `total_usd` is not floored at zero; penalties can drive it negative, and issuing such an invoice drives `settled_to_date_usd` down — `calc.py:336`, `derive.py:138-153`
- §3.3 ¶4 — insert — ambiguity — grounding and restoration are mutually exclusive per recompute: the grounding test fires first and returns, so an over-allocated base restores nothing (reachable over-grounding leaves tails permanently grounded) — `derive.py:27-36`
- §3.6 ¶1 — insert — ambiguity — filing an estimate has no month-status precondition, and immediately moves the month's `estimated_passthrough_total_usd` and `version` — `routes/passthrough.py:35-63`
- §3.6 ¶2 — insert — ambiguity — named `ERR_INVALID_STATE` as the month-status refusal, and pinned that adjudication carries no month-status test — `routes/passthrough.py:91-92,111-112`
- §3.7 ¶6 — insert — ambiguity — the three conditions are the whole test: the base's `lifecycle_status` is irrelevant and the set is not month-scoped, so two months of one agreement carry an identical `brand_penalty_usd` — `calc.py:197-215`
- §3.7 ¶8 — insert — ambiguity — the staleness trigger list is exhaustive; pass-through activity after the close rebuilds figures but stales/voids nothing; leg completion stales nothing; an already-`STALE` scorecard is not re-staled — `derive.py:127-134,208-211`, `routes/passthrough.py:129-130`

Verified already-pinned in pass B's slice (abridged): `leg_variable_amount` round-at-leg-then-sum discipline; `included_legs` variant filters and departure ordering; `fixed_component` and `ownership_aircraft_count` filters; `completion_factor` eligible-base composition, the `eligible <= 0 → 100.00` convention and numerator/denominator asymmetry; both zero-denominator conventions; all nine band thresholds and their favourable-side-inclusive boundaries; the forfeiture branch; point value 12,000.00, the three-way incentive `min` and the penalty `min`, penalty stored as a non-negative magnitude; severity weights 500/2500/7500 with sum-then-round-then-cap at 25,000.00; FUEL uncapped, 0.10/0.05 tolerances, `min(actual, ceiling)`; admin-fee tiering with inclusive upper bounds pinned to the Step-2 base; signed `variance_usd`; the 0.65 training credit floored before addition and the three-band posture; `metric = published − controllable − uncontrollable` and `departure_ledger_total` as the three-position sum; both ledger positions opening at `published_departures`; the `open_leg_count == 0` close gate and single `PUBLISHED` scorecard; `make_scorecard_stale` voiding both variants with `AUTO_SCORECARD_STALE`; the audit-creation/closure fan-out with remediation-verified and acknowledge deliberately non-staling; recompute rebuilding all 12 fields with `recompute_count` +1; invoice components frozen at creation.

### Pass C — entity-lifecycle layer (22 edits: 19 ambiguity, 3 mismatch)

453 lines / 102,720 → 110,475 chars; all edits in-paragraph.

- §3.1 ¶4 — revise — **mismatch** — `termination_reason` is validated as a required non-blank string but discarded; no such attribute is ever persisted or echoed — `routes/agreements.py:90`
- §3.1 ¶4 — insert — ambiguity — hop 2 is scoped by `assigned_base_id`, not the tail's `agreement_id`; no staffing recompute runs in the cascade, so closed bases keep all six derived figures and in-service/grounded tails stay put — `routes/agreements.py:103-117`
- §3.2 ¶1 — insert — **mismatch** — the "three-letter `station_code`" is unenforced (non-blank string only, any length); uniqueness ignores `lifecycle_status` (a `CLOSED` base still reserves its code); base creation has no agreement-`status` precondition — `validate.py:132-134`, `routes/crew_bases.py:24-38`
- §3.2 ¶2 — insert — ambiguity — `hire_class_date` is calendar-checked only, never compared to the clock; `employee_ref` uniqueness spans every pilot status including terminal ones; hiring tests neither base `lifecycle_status` nor agreement `status`; the recompute moves nothing so the base's audit fields do not move — `routes/pilots.py:38-61`
- §3.2 ¶6 — revise — **mismatch** — the recompute-trigger list omitted hiring; impl recomputes on hire too, each recompute carrying the grounding/restoration pass; only recomputes that actually move a figure refresh the base's audit fields — `routes/pilots.py:60`, `derive.py:50-54`
- §3.2 ¶7 — insert — ambiguity — attrition tests neither agreement nor base `ACTIVE` (unlike advancement); a `PIPELINE` departure moves no figure so the base's audit fields stay put — `routes/pilots.py:104-126`
- §3.3 ¶1 — insert — ambiguity — `tail_number` uniqueness spans every status; `assigned_base_id` need not belong to the named `agreement_id` (no cross-agreement error at registration); neither base nor agreement status is tested — `routes/aircraft.py:32-46`
- §3.3 ¶2 — insert — ambiguity — the base-`CLOSED` induction refusal is `ERR_INVALID_STATE`, taken after the tail's own status check and before either capacity test — `routes/aircraft.py:88-96`
- §3.3 ¶5 — insert — ambiguity — `transition_reason` and `target_ownership` are both required, and `target_ownership` may name the form the tail already carries — `routes/aircraft.py:111-113`
- §3.3 ¶5 — insert — ambiguity — completing the transition retains `transition_reason` and `target_ownership` rather than nulling them; `inducted_at` survives both steps — `routes/aircraft.py:141-143`
- §3.4 ¶4 — insert — ambiguity — `flight_number`, `origin`, `destination` are unconstrained non-blank strings: no length/alphabet check, no uniqueness, no origin≠destination rule — `routes/flight_legs.py:74-76`
- §3.4 ¶5 — insert — ambiguity — the captain's crew base `lifecycle_status` is not consulted; a `CLOSED` base does not disqualify a `LINE_QUALIFIED` captain — `routes/flight_legs.py:91-94`
- §3.4 ¶6 — insert — ambiguity — the turn buffer scans every same-tail leg service-wide regardless of month/agreement, always on the other leg's *scheduled* interval even when already `COMPLETED` — `routes/flight_legs.py:100-108`
- §3.4 ¶7 — insert — ambiguity — duty window lower bound inclusive (`[dep−24h, dep+24h)`); scans all months/agreements; always sums `planned_block_hours` even for completed legs — `routes/flight_legs.py:111-121`
- §3.4 ¶8 — insert — ambiguity — all four completion fields required; `enplaned_bags`/`mishandled_bags` are JSON integers with no minimum and no mishandled<=enplaned relation — `routes/flight_legs.py:171-175`
- §3.4 ¶10 — insert — ambiguity — cancellation does not consult the tail's status; a grounded or transitioning tail's leg may still be cancelled — `routes/flight_legs.py:206-221`
- §3.4 ¶11 — insert — ambiguity — reinstatement re-runs no turn buffer, no duty cap, no captain-qualification and no cross-agreement test — `routes/flight_legs.py:244-273`
- §3.5 ¶5 — insert — ambiguity — classification leaves `dispute_round` and `dispute_note` untouched (no reset on reclassification) — `routes/cancellation_claims.py:55-57`
- §3.5 ¶7 — insert — ambiguity — finalization imposes no test on the month's status; admissible while `OPEN`, `CLOSED` or `SETTLED` — `routes/cancellation_claims.py:86-99`
- §3.7 ¶4 — insert — ambiguity — `findings_count` has no upper bound; raising an audit tests neither base `lifecycle_status` nor agreement `status` — `routes/brand_audits.py:33-51`
- §3.7 ¶5 — revise — ambiguity — a `to_remediation_status` of `NOT_STARTED` (or any non-single-step value) is `ERR_INVALID_STATE`, checked before `ERR_EVIDENCE_REQUIRED`; `evidence_ref` is optional, stored whenever supplied, and omission leaves the stored value untouched rather than clearing it — `routes/brand_audits.py:91-105`
- §3.9 ¶3 — insert — ambiguity — counter and revise-offer each test the agreement for `EXTENSION_PENDING` (after the round's own status); accept and withdraw test only the round and drive the agreement to `ACTIVE` unconditionally — `routes/negotiations.py:55,84,125,143`

Verified already-pinned in pass C's slice (abridged): round-count semantics and supersession-to-`WITHDRAWN`; stale-version check ahead of the `ACTIVE` check on round opening; both round-exhaustion boundaries ordered before `ERR_EXTENSION_TERM_NOT_LATER`; revise-offer not resetting `counter_round`; the SoD role mapping on accept and its placement after the state guard; activation requiring a live `ACTIVE` base; termination refused while a month is `OPEN`; both induction capacity tests and their staffing-before-allocation order; `ERR_AGREEMENT_NOT_ACTIVE` ahead of the terminal guard on induct/advance; `ERR_AIRCRAFT_HAS_OPEN_LEGS` scoped to `SCHEDULED` legs; base-`ACTIVE` required on `PIPELINE → IN_TRAINING` only; the attrition destination mapping; the leg-scheduling guard order; the 35-minute and 16.000 inclusive boundaries; the 14-minute inclusive on-time grace; the ledger-overflow formula; the four claim state sets and the five-hop finalization cascade; brand-audit two-dimension independence and audit-create/finding-close as the only staling brand events.

### Cross-pass notes carried forward (no edit made)

Pass C flagged, without changing it, that `derive.py:27-36` measures the grounding shortfall against `assigned_aircraft_count` (which still counts already-grounded tails) while drawing candidates only from `IN_SERVICE`, so repeated recomputes on a persistently over-allocated base ground progressively more tails until the `IN_SERVICE` set empties. §3.3 ¶3 as written already describes exactly this per-recompute arithmetic and covers exhaustion with "An empty candidate set is a silent no-op", so the PRD is faithful either way; recording it here because it is the kind of behaviour that reads as accidental. No pass reported an earlier pass's edit as wrong.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` — 46 diff hunks, +18,775 chars. (This is the specific failure mode the three-pass split was designed to prevent.)
- Structure intact: 5 top-level sections, **62** GET/POST endpoint rows, **45** `ERR_` catalogue rows — unchanged from PRD.md. File ends at the complete final table row `| ERR_EXTENSION_TERM_NOT_LATER | 422 Unprocessable Entity |`, not mid-sentence.
- No file under `workspace/implementation/` has an mtime later than the Step 7 sweep, so the green `results.{1..8}.json` (94/94 × 8, written 07:46) still describe the implementation exactly as it stands. Steps 8 and 9 were documentation-only, as required.

**Pipeline complete.** All nine steps finished; `workspace/PRD_COMPLETED.md` is written.
