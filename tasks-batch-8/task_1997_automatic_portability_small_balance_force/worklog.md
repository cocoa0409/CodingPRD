# Worklog — task_1997_automatic_portability_small_balance_force

## Step 1: Create Task Directory — 2026-08-15T05:27:00.000Z

Pre-created by the invoking pipeline: `tasks/task_1997_automatic_portability_small_balance_force/` and `workspace/` already existed on entry; no index scan or directory creation performed by this orchestrator.

## Step 3: Copy Shared Files — 2026-08-15T05:28:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1997_automatic_portability_small_balance_force/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-15T06:21:00.000Z

All three artifacts are written and clean. Summary:

## Task 1997 — Automatic Portability & Small-Balance Force-Out: scaffold complete

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/`):
- `SCAFFOLD.yaml` (1154 lines) — §1.0–§1.7 only; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (875 lines) — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` (1193 lines) — single `scaffold_corner_design:` key

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (986 calls scanned, exit 0)

**Requested counts:**
- Entities: **13** (Recordkeeper, Plan, Participant, DistributionBatch, DistributionCase, Notice, Election, SafeHarborIRA, IRAFeeAssessment [event, common_fields:false], Check [self-referential supersedes chain], MatchCandidate, Transfer, FiduciaryReview)
- State machines: **11** — four cyclic (case NOTIFIED↔IDENTIFIED re-notice, IRA OPEN↔MATCHED↔TRANSFER_PENDING→OPEN, batch EXECUTED↔RECON_EXCEPTION, recordkeeper ACTIVE↔SUSPENDED)
- Endpoints: **65** (flat topology, api_prefix `""`, incl. `POST /sweeps/run` and `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: **30** (auth 401/403 through state 409, safety/temporal/referential/constraint/fiscal 422, OCC 412)
- Roles: **4** (Participant entity_backed; PlanSponsor, ProviderOps, FiduciaryReviewer opaque; segregation-of-duties between batch executor and reviewer)
- §1.8 instances: **22 non-stub** (dual_variant 2, combinatorial 3 [modes a/b/c], non_linear_sm 3, transitive_cascade 2 [depth-3 recordkeeper-exit and depth-3 check-escheat], priority_pair 2 [state>fiscal, safety>referential], boundary 3 [money band, inclusive deadline, 0.850 score], cross_entity 3, temporal_overlap 2 [half-open review periods vs open-ended batch occupancy], compensating_invariant 2 [IRA cents conservation, check-chain obligation])
- §1.9 instances: **48 non-stub + 4 excluded_because stubs** (52 total), spanning all nine claim-guide sections; every one of the 30 error codes has at least one triggering instance

**Key design decisions:** all money integer cents with round-half-up; every formula-derived assert pre-computed as a literal (fee 510 vs 500 day-count divergence, net check 75006 vs forbidden 75005 rounding order, transfer 299243 evaluation-order pin, match scores 0.652/0.847/0.850/0.910); OCC per §1.2.1 only on true races (election supersede, plan config PATCH); two unreachable error codes were caught and removed during audit (ERR_TRANSFER_IN_FLIGHT, ERR_CONFIRMED_MATCH_EXISTS — both fully masked by state preconditions), and the match-confirm floors were re-tiered (REVIEW_FLOOR 0.400 / CONFIRM_FLOOR 0.650) so ERR_SSN_GATE_FAILED and ERR_MATCH_SCORE_BELOW_THRESHOLD are actually reachable.

## Step 4: Generate PRD — 2026-08-15T06:40:00.000Z

PRD generation complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/workspace/PRD.md` (346 lines). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or referenced.

## Summary

**Line count:** 346

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 RBAC (headers, 4 roles, identity semantics incl. entity-backed `Participant` vs opaque roles, SoD), 2.2 API Response Structure (verbatim block), 2.3 Pagination (+ all 26 list-filter params named), 2.4 Logical Clock (`to_iso8601`/`current_utc`, startup default `2026-08-01T00:00:00Z`), 2.5 Common Resource Properties (incl. append-only `IRAFeeAssessment` exception: no `updated_at`/`version`), 2.6 Monetary Representation & Day-Count Conventions, 2.7 OCC (all three version-guarded writes), 2.8 Recordkeeper Network Status & 3-link exit cascade, 2.9 Validation Order (all 11 priority tiers rendered as an ordered cascade), 2.10 Nested/Referenced Retrieval (left-to-right 404)
- §3 Business Logic — 3.1 Recordkeepers & Plans, 3.2 Participant Registry & Address Hygiene, 3.3 Batch Assembly/Lock (valuation variants + force-out bands with inclusive boundaries), 3.4 Notice Delivery & Election Window (30-day inclusive deadline, supersede/void), 3.5 Execution: Checks/Withholding/Direct Rollovers (pinned per-component rounding, forbidden reorder named), 3.6 IRA Establishment/Fees/Opt-Out ($60 fee, ACTUAL_365 vs THIRTY_360 with 510/500-cent worked comparison, balance floor, monthly duplicate gate), 3.7 Matching & Transfers (weights 0.55/0.30/0.15, bands 0.400/0.650/0.850 with SSN gate order, pinned transfer-amount evaluation order), 3.8 Stale Checks/Reissue/Escheatment (180-day exclusive staleness, 90-day warning lead, 1095-day dormancy, sweep counters), 3.9 Reconciliation & Fiduciary Review (counter formulas, half-open overlap with adjacency, attestation cascade)
- §4 Endpoint Definitions — 65 rows, 4 columns (Method/Path/Description/Authorized Roles), all 65 scaffold endpoints present
- §5 Error Code Catalogue — 30 rows, 2 columns, all 30 scaffold errors present

## Hard Contract Reports

**Contract 1 — Field-Name Coverage:** 117 required names (all `entities[].fields[].name`, all endpoint `input`/query/path params, OCC fields, sweep/clock output fields, common fields) — 117 present as backticked tokens, 0 missing. **PASS**

**Contract 2 — Rule Coverage (manual walk + mechanical assist):** validations with priority: 11 checked, 11 expressed in the §2.9 ordered cascade; OCC rejections: 3 checked (`expected_plan_version`, `expected_case_version`, `expected_ira_version` — endpoint + field + `ERR_STALE_VERSION`/412 each named), 3 expressed; state-machine transitions: 48 checked across 11 machines, 48 fully expressed (from/to states, preconditions paired with error IDs, side effects incl. the recordkeeper-exit, transfer-rejection, and escheatment 3-link cascades); calculations: 9 checked, 9 fully expressed in precise prose (reconstruction-tested: vested balance variants, threshold bands with boundary pins, per-component withholding rounding order, both day-count fee formulas with worked 510/500 example, pinned transfer-amount order, match weights/bands, inclusive notice window, exclusive staleness/dormancy boundaries, reconciliation counters); validation conditions: 11 tiers all matchable to their 30 error IDs in §2/§3 prose; endpoint side effects/applies_to: 65 checked and expressed (incl. per-endpoint `version` increments and notice-type state gates); field structured content: all defaults/constraints reconstructible (thresholds 100,000/700,000 cents, rate 0–0.15, `vesting_percent` 0–100 default 100, `ACTUAL_365` default, null-defaults, etc.); sibling-branch symmetry: BOUNCED/RETURNED_MAIL, ACCEPTED/REJECTED, ACTUAL_365/THIRTY_360, SEPARATION_DATE/PROCESSING_DATE all rendered at equal density. **PASS**

**Contract 3 — §3 Path Purity:** 577 backticked tokens scanned in §3; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0. **PASS**

## Step 5: Generate Unit Tests — 2026-08-15T07:05:00.000Z

All green. Here is the final summary.

---

## Summary

**Task**: `task_1997_automatic_portability_small_balance_force` — full Stage 1 + Stage 2 test generation per the `prd-bench-unit-test-generator` skill.

### Test counts
- **Queue A (Difficulty)**: 44 tests — all 22 instances in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` translated with exactly 2 tests each (9 rules × 2 instances × 2 tests).
- **Queue B (Corner)**: 48 tests — all 48 non-stub instances in `SCAFFOLD_CORNER_DESIGN.yaml` translated with exactly 1 test each.
- **Total: 92 tagged tests**, all collected cleanly by pytest.

### Instances skipped
None. Every non-stub instance in both queues passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability). The 4 `excluded_because:` stubs in the corner index (`provisional_quote_uses_separation_variant`, `match_sibling_expiry_on_confirm`, `recordkeeper_exit_cascade_corner`, `net_check_at_zero_state_rate`) were not translated per spec; their cross-references all resolve to real difficulty instances that own those assertions.

### Files created
`test_helpers/` (Stage 1):
- `__init__.py`, `types.py`, `api_client.py` (57 endpoint methods), `api_errors.py` (31 errors, framework-registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (composite chains: locked batch → notified → elected → executed → IRA established → matched → transfer-ready → reconciled → reviewed)

`test_suite/` (Stage 2):
- `conftest.py`
- `test_01_valuation_and_fee_variants.py` (dual-variant calc)
- `test_02_combinatorial_formulas.py` (match score, withholding rounding order, transfer evaluation order)
- `test_03_state_machine_cycles.py` (renotice cycle, transfer-reject reopen, recon-exception cycle)
- `test_04_transitive_cascades.py` (recordkeeper-exit depth-3, check-escheat depth-3)
- `test_05_error_priority_pairs.py` (state-beats-fiscal, safety-beats-referential)
- `test_06_boundary_precision.py` (force-out bands, inclusive deadline, 0.850 auto-confirm)
- `test_07_cross_entity_dependencies.py` (case→batch, transfer→recordkeeper, review→batch)
- `test_08_temporal_overlap_and_occupancy.py` (half-open review overlap, batch single-occupancy)
- `test_09_compensating_invariants.py` (IRA money conservation, check-chain obligation)
- `test_10_entities_basics.py` through `test_16_concurrency_and_consistency.py` (corner queue)

`lint_tags.py` (audit script, kept at task root for re-verification).

### Stage 2 lint verdict
**PASS** — AST-based audit confirms: every test has exactly one `Design:` tag as the last docstring line; every tag resolves to a real instance; all 22 difficulty instances have ≥2 tests; all 48 non-stub corner instances have ≥1 test; no stub was translated; no broken stub cross-references. Separately verified all 160 quoted PRD citation spans survive literal (whitespace-normalized) grep of `workspace/PRD.md` — 17 initially elided quotes were rewritten to full verbatim sentences to satisfy C1/C3.

## Step 6: Generate Implementation — 2026-08-15T07:10:00.000Z

Done. Summary of the delivered implementation:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/workspace/implementation/`:
- `app.py` (~1,300 lines) — Flask entry point, error handlers, and all 65 route handlers
- `core.py` (~700 lines) — logical clock (default `2026-08-01T00:00:00Z`, no wall-clock fallback), in-memory `DB` dicts (13 entity stores, empty at boot), envelope builders (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`), auth middleware (`X-User-ID`/`X-User-Role`, 4 roles), shape validators, Decimal-based calculations, serializers (3-fractional-digit `Z` timestamps; `IRAFeeAssessment` serialized with no `version`/`updated_at` per the append-only-ledger rule)
- `start.sh` — executable; guarded `pip install` (no-op once flask importable), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4`

## Endpoint count
**65/65** endpoints implemented — the full PRD §4 table (recordkeepers 6, plans 5, participants 4, batches 7, cases 5, notices 4, elections 4, IRAs 5, fee-assessments 2, checks 6, match-candidates 5, transfers 4, fiduciary-reviews 6, sweeps 1, clock 1).

## Key fidelity points implemented
- Validation precedence per PRD §2.9 (auth → role → ownership → shape → existence → state → compliance → temporal → referential → occupancy/OCC → fiscal), verified by the priority-pair scenarios (state-beats-fiscal on IRA establish; safety-beats-referential on transfers)
- OCC with `ERR_STALE_VERSION`/412 on plan PATCH, election submit, transfer initiate (digit-strings coerced, since test recipes pass captured versions as strings)
- Calculations pinned by the design files: per-component withholding rounding (100007 → 20001/5000/75006), ACTUAL_365 vs THIRTY_360 fees (510/31d vs 500/30d, then 493 next month), transfer evaluation order (snapshot 299490 − accrual 247 = 299243), match-score banding with SSN gate (0.850 auto-confirm, 0.847 candidate, 0.450 gate-capped), inclusive election/stale boundaries, exclusive dormancy (>1095 days)
- Case version semantics pinned by the difficulty design: batch lock does NOT bump case version (case is at version 2 after create + notice delivery); all status transitions do
- Cascades: recordkeeper exit (plans → matches → IRAs, `last_activity_at` untouched), escheat void (check → case → batch), transfer reject unwind, IRA close match expiry, supersede chains
- In-memory dicts only; zero seeding at startup; fresh boot verified to return `total_count: 0` on all collections

## Boot verification
Started the server four separate times via `PORT=18997 bash start.sh` (fresh process each time, including after code edits and after killing prior instances). Each boot: empty store confirmed, then ~135 smoke assertions run across five scripts covering every entity, state machine, calculation, cascade, RBAC rule, and error precedence pair — all passing, including a full happy-path lifecycle (register → activate → plan → participant → batch → case → lock → notice → election → execute → IRA → fee → match → transfer → reconcile → review → attest → REVIEWED) and the final fresh-boot probe (`POST /recordkeepers` 201, `POST /_clock/set_current_utc`, `POST /sweeps/run` all returning correct envelopes).

## Step 7: Run Tests and Iterate — 2026-08-15T07:35:00.000Z

All 8 rounds pass 92/92. Exit condition met.

## Summary

- **Iterations run:** 2 (iteration 1: 89/92 across all 8 rounds; iteration 2: 92/92 × 8 rounds, zero failures).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/test_suite/test_14_endpoints_listing.py` — added missing `get_success_data` to the `test_helpers` import; caused `NameError` in `test_list_pagination_envelope` and `test_filtered_list_cases_by_status` (both PRD-faithful tests, plain import omission).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/test_suite/test_09_compensating_invariants.py` — `test_void_reissue_preserves_obligation`: corrected the expected net check amount from 75000 to 80000. Setup uses the default plan (`state_withholding_rate` = 0 per PRD §3.1), so PRD §3.5's pinned per-component rounding gives fed = round(100000×0.20) = 20000, state = 0, net = 100000 − 20000 − 0 = 80000. The old expectation encoded exactly the "net a combined 25% rate in a single step" order that PRD §3.5 names as forbidden, and contradicted the same test's own `state_withholding_cents == 0` assertion. Rule is verbatim-covered and uniquely derivable → test bug, fixed the assertion.

- **Fixes applied to `implementation/`:** none — the implementation was already PRD-correct on every tripped assertion (it returned the PRD-mandated 80000; the two NameErrors never reached it). No endpoint, field, or check was added/removed/weakened.

- **Flakiness note:** iteration-1 stdout showed apparent extra `FAILED` lines for `test_cashing_successor_settles_exactly_once`, but all 8 authoritative `results.*.json` files recorded it as passed — the lines were interleaving artifacts of 8 concurrent pytest verbose streams sharing one output file (pytest prints the nodeid before the verdict). Confirmed clean in iteration 2: all 736 test events passed.

## Step 8: Finalize PRD — 2026-08-15T07:42:00.000Z

Investigation complete. PRD_FINALIZED.md is written and byte-identical to PRD.md — the zero-edit outcome the task brief explicitly sanctions, since both step_7_diff items are confirmed pure test bugs with no PRD silence and no PRD/impl mismatch.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 346 lines vs 346 lines, 0% delta (byte-identical; `diff -q` confirms).

**Changes:** none — zero edits committed.

### Per-diff-item investigation (in lieu of a per-edit log, since no edit was made)

**Item 1 — `test_14_endpoints_listing.py` missing `get_success_data` import**
- (a) Subject: list pagination envelope and exact-match filters (PRD §2.3), as exercised by `test_list_pagination_envelope` and `test_filtered_list_cases_by_status`.
- (b) Impl paths enumerated and read: `core.py:337-373` (`list_response`, the single shared pagination/filter helper) plus all 14 list-endpoint callsites in `app.py` (`list_recordkeepers`:83, `list_plans`:203, `list_participants`:311, `list_batches`:374, `list_cases`:508, `list_notices`:599, `list_elections`:710, `list_iras`:799, `list_fees`:892, `list_checks`:953, `list_matches`:1134, `list_transfers`:1243, `list_reviews`:1335). Behavior verified: limit defaults to 10 and is clamped to [1,100]; offset defaults to 0 and is floored at 0; envelope carries `limit`/`offset`/`total_count`/`has_more`; filters are exact-match on like-named fields; ordering is insertion order (created-at ascending under the single logical clock). All consistent with PRD §2.3 verbatim. The two tests quote §2.3 verbatim and died on a `NameError` inside the test module itself before ever reaching the server — a plain import omission, not a behavioral divergence.
- (c) No wording change warranted.

**Item 2 — `test_09_compensating_invariants.py::test_void_reissue_preserves_obligation` (75000 → 80000)**
- (a) Subject: net-check withholding computation (PRD §3.5) and the plan default `state_withholding_rate` (PRD §3.1).
- (b) Impl paths enumerated and read: `core.py:406-410` (`net_check_withholding`: `fed = rhu(gross × 0.20)`; `state = rhu(gross × state_rate)`; `net = gross − fed − state`); its callsite at `app.py:926` (CASE_CASH_OUT check issuance); the parallel IRA-close check path at `app.py:834` (both withholding components zero, payable equals gross — matches PRD §3.6's "no withholding at all"); and the plan default at `app.py:175` (`state_withholding_rate` defaults to 0). The test's `_setup` (via `setup_executed_batch_elected_cash`, docstring "default rate 0") uses that default plan, so fed = 20000, state = 0, net = 80000 — exactly what the impl returns and what PRD §3.5's pinned per-component rounding uniquely yields. PRD §3.5 even names the old test's logic ("netting a combined rate against the gross in a single step") as the "forbidden order," and 75000 would have contradicted the same test's own `state_withholding_cents == 0` assertion. Rule is verbatim-covered and uniquely derivable → test bug, no PRD silence.
- (c) No wording change warranted.

**Relevant file paths:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/workspace/PRD_FINALIZED.md` (produced; identical to PRD.md)
- `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/workspace/implementation/core.py` (lines 337-373, 406-410)
- `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/workspace/implementation/app.py` (lines 175, 834, 926)

## Step 9: Complete PRD — 2026-08-15T08:00:00.000Z

All changes verified: 22 in-place line replacements, no sections added, line count unchanged. Final summary:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1997_automatic_portability_small_balance_force/workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md 346 lines / 55,442 chars → PRD_COMPLETED.md 346 lines / 59,646 chars (**+0 lines, +4,204 chars**). All edits are inline inserts/revisions within existing paragraphs; no new sections or paragraphs.

**Counts:** 27 ambiguity-pins, 6 mismatch-revisions (22 diff hunks total).

### Changes

- **§2.3** — insert — ambiguity — `limit`/`offset` out-of-range values are clamped (not rejected), non-integer values are `ERR_INVALID_REQUEST`; creation-timestamp ties keep insertion order; `total_count` counts the filtered set; unknown query params ignored — `core.py:337-374`
- **§2.4** — insert — ambiguity — all entity timestamps read the logical clock; only the envelope `api_request_timestamp` is wall-clock — `core.py:125-138, 151-155`
- **§2.5** — insert — ambiguity — `version` starts at 1 on creation — `core.py:131`
- **§2.5** — insert — ambiguity — client-supplied system-managed fields on create are ignored — `core.py:125-132`
- **§2.5** — insert — ambiguity — datetime inputs accept bare `YYYY-MM-DD` (midnight UTC) and offset-less values (read as UTC); date fields stay strict — `core.py:43-59`
- **§2.7** — insert — ambiguity — expected-version fields accept JSON int or decimal-integer string — `core.py:302-313`
- **§2.7** — revise — mismatch — "Endpoints not listed here do not accept a version field at all" → they ignore it — `app.py` (validators read only declared fields)
- **§2.8** — revise — mismatch — `network_reachable` formula gains the plan-status condition: a `TERMINATED` plan is never reachable — `core.py:461-471`
- **§2.8** — insert — ambiguity — recordkeeper-driven recompute bumps a plan's `version` only when the derived value actually changes — `app.py:94-108`
- **§2.9 tier 3** — insert — ambiguity — case/election/IRA-scoped ownership checks fetch the resource first (404 precedes 403); `PATCH /participants/{id}` compares the path id before existence — `app.py:325-327, 666-669, 727-730, 816-819`
- **§2.9 tier 4** — insert — ambiguity — `POST /distribution-cases/{id}/elections` and `PATCH /participants/{id}` locate the path target before body validation, so 404/403 precede 400 there — `app.py:666-671, 328-340`
- **§3.1** — insert — ambiguity — duplicate `recordkeeper_code` rejected with `ERR_INVALID_REQUEST` — `app.py:69-71`
- **§3.1** — revise — mismatch — activation recomputes reachability only for non-terminated plans and increments only changed plans' versions (was "every plan whose accepts_incoming_transfers is true — incrementing those plans' version values") — `app.py:94-120`
- **§3.1** — insert — ambiguity — registration-time threshold/rate violations are `ERR_INVALID_REQUEST` (400) — `app.py:180-182`
- **§3.1** — revise — mismatch — update bounds validated against the merged configuration, including the cash-out ≥ 1 cent lower bound (was only "push above the rollover threshold") — `app.py:234-240`
- **§3.1** — insert — ambiguity — configuration update is not gated on `plan_status`; a TERMINATED plan may be patched — `app.py:214-256`
- **§3.2** — insert — ambiguity — duplicate `ssn_hash` rejected with `ERR_INVALID_REQUEST` — `app.py:291-293`
- **§3.2** — insert — ambiguity — `mailing_state` two-letter form is conventional, not validated — `app.py:286`
- **§3.2** — insert — ambiguity — any successful address PATCH marks `VALID` and bumps version, even one changing no field — `app.py:330-342`
- **§3.3** — insert — ambiguity — lock finalizes only cases still `IDENTIFIED`, and lock finalization does not increment case `version` or refresh `updated_at` — `app.py:395-406`
- **§3.4** — insert — ambiguity — only a `SENT` notice accepts `DELIVERED`/`BOUNCED`; other states → `ERR_INVALID_STATE` — `app.py:619-633`
- **§3.4** — revise — mismatch — `ESCHEAT_WARNING` gate: case `EXECUTED` always qualifies (voided-but-uncashed counts) and any `OPEN` IRA qualifies — no dormancy-proximity test (was "uncashed check outstanding"/"drifting toward dormancy") — `app.py:578-585`
- **§3.4** — insert — ambiguity — marking an already-`BAD_ADDRESS` participant is a no-op with no version increment — `core.py:540-543`
- **§3.6** — revise — mismatch — closure sets `balance_cents` to zero directly; the closing check is not routed through `in_flight_cents` (was "through the in-flight check linkage") — `app.py:845`
- **§3.6** — insert — ambiguity — the `IRA_CLOSE` check carries the standard 180-day `stale_after` — `app.py:839`
- **§3.6** — insert — ambiguity — closure refreshes `last_activity_at` — `app.py:847`
- **§3.7** — insert — ambiguity — probe with source plan's `auto_portability_enabled` false → `ERR_INVALID_STATE` — `app.py:1085-1086`
- **§3.7** — insert — ambiguity — `name_similarity` outside [0,1] → `ERR_INVALID_REQUEST`; two-decimal granularity not enforced — `app.py:1076-1078`
- **§3.7** — insert — ambiguity — a named `match_candidate_id` that is not this IRA's `CONFIRMED` match → `ERR_INVALID_STATE` — `app.py:1197-1198`
- **§3.7** — insert — ambiguity — the most recently delivered prenotice governs the opt-out window — `core.py:505-513`, `app.py:1199`
- **§3.7** — insert — ambiguity — a `rejection_reason` supplied with `ACCEPTED` is ignored (stays null) — `app.py:1262-1294`
- **§3.8** — insert — ambiguity — reissuing an escheatment-voided check → `ERR_INVALID_STATE` — `app.py:1022-1023`
- **§3.8** — insert — ambiguity — sweep IRA escheatment refreshes `last_activity_at` to the sweep instant — `app.py:1437`
- **§3.9** — insert — ambiguity — review action by a non-named reviewer → `ERR_FORBIDDEN_ROLE` (403) — `app.py:1349-1354`

**Method notes:** Every endpoint, state transition, formula, validation, default, error path, and serializer field in `app.py` (1,458 lines) and `core.py` (780 lines) was walked against the PRD. Everything else in the PRD — all calculation formulas (vesting, withholding, fee day-counts incl. the 510/500-cent examples, match scoring/banding), all state machines, all gates, the tier-ordered error precedence, the filter lists, role tables, and the error catalogue — matched the implementation exactly and was left untouched. Tests were consulted only as cross-reference, never as authority.
