# Worklog — task_1232_lease_renewal_rent_increase_administration

## Step 1: Create task directory — 2026-08-12T03:36:00.000Z

Pre-assigned output folder `tasks/task_1232_lease_renewal_rent_increase_administration` with `workspace/` subdirectory already exists (created by pipeline harness). Step 1 auto-index scan skipped per instructions; directory verified present and empty.

## Step 2: Generate scaffold — 2026-08-12T04:27:00.000Z

Scaffold generation complete for task 1232 (Lease Renewal & Rent Increase Administration). All three artifacts are written and lint-clean.

**Files produced** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1232_lease_renewal_rent_increase_administration/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (verified no `scaffold_difficulty_design`/`scaffold_corner_design` keys leak in)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key, 18 instances (2 per each of the 9 Difficulty Rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key, 61 instances (52 real test recipes + 9 `excluded_because` stubs citing difficulty instances)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (41 endpoints, 9 entities, 18 §1.8 + 52 §1.9 active instances, 629 calls scanned, 0 violations.)

**Design shape** (maximum difficulty per the brief):
- Archetype: compliance/audit primary × pricing-engine secondary; flat topology, cyclic state machines, hierarchical_override roles with segregation-of-duties overlays, OCC on Lease/Property versions.
- 9 entities (RentCapPolicy, Property, Unit, Resident, Lease, RenewalOffer, ConcessionApproval, NonRenewalNotice, RenewalDocument), 41 endpoints, 40 error codes, 8 calculations, 5 state machines, 2 OCC concurrency rules, 5 roles.
- Load-bearing mechanics: provisional-vs-executed rent divergence under mid-negotiation policy drift (211000 vs 209000 cents), nested-rounding MTM premium with a pinned round-twice order (242637 vs the forbidden single-round 242638), tiered statutory notice (strictly-greater 500 bps threshold), staggering term selector with explicit load/tie-break rules, 3-tier concession authority ladder (300/800/2000 bps) with per-person SoD, half-open lease overlap vs quarterly repositioning aggregate quota (the two rule-8 interval semantics), and compensating invariants (rescission restores lease economics verbatim; notice rescission restores MTM-vs-ACTIVE status verbatim).

**Two design flaws caught and fixed during recipe replay:** (1) DRAFT-offer sweep expiry made the late-issue `ERR_NOTICE_WINDOW_MISSED` path unreachable — DRAFTs now persist and fail at issue time; (2) the notice-enforcement cascade into ACCEPTED offers was provably unreachable given statutory leads — rule-4 was rebuilt as a serve-triggered depth-3 chain (serve → lease noticed → offer withdrawn → concession voided) plus a create-supersede depth-2 chain.

## Step 3: Copy shared files — 2026-08-12T04:28:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1232_lease_renewal_rent_increase_administration/workspace/INSTRUCTION.md` (1424 bytes, verified on disk).

## Step 4: Generate PRD — 2026-08-12T04:37:00.000Z

All verification checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1232_lease_renewal_rent_increase_administration/workspace/PRD.md`.

## What was generated

A prose PRD for the lease-renewal-administration domain, structured as:

- **§1 Introduction** — 2 paragraphs from a business-pain-point angle (renewal-cycle revenue/compliance pressures, logical clock as governed input).
- **§2 Global Specifications** (10 subsections): RBAC with per-role `identity` translations (Resident entity-backed; four staff roles opaque), the §2.2 envelope block emitted verbatim from `section-2.2-response-structure.md`, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (default `2026-05-01T00:00:00Z`, pinned 4-step sweep order), common resource properties, cents/basis-points/round-half-up discipline, OCC (both rules with exact error IDs and 412), statutory rent-cap/notice primitives, the full 11-stage validation pipeline with stage-10 sub-order (a)–(h) and per-error HTTP variations, and the three cross-entity cascade commitments.
- **§3 Business Logic** (8 subsections, lifecycle-grouped): portfolio foundations → lease onboarding/term geometry/MTM conversion → offer generation (six-step pricing pipeline, staggered term selection, notice tiers) → issuance/response/negotiation loop → concession authority (300/800/2000 bps tiers, SoD, absolute max) → non-renewal notices (5 serve guards, repositioning quota, 3-link serve cascade, cure/confirm/enforce) → document execution/rescission (final-variant recompute, `prior_*` snapshot restore, 3-day window) → retention metrics (TRAILING/PIPELINE) and expiration forecast.
- **§4 Endpoint table** — 41 rows, 4 columns only. **§5 Error catalogue** — 39 rows, 2 columns only, no trigger conditions.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 66 required, 66 present, 0 missing
- endpoints[].request_body/input: 18 required, 18 present, 0 missing
- endpoints[].query_params/path_params: 16 required, 16 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (§2.9 ordered pipeline incl. stage-10 sub-order), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_lease_version/expected_property_version + ERR_STALE_LEASE_VERSION/ERR_STALE_PROPERTY_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 27 checked, 27 fully expressed across §2.4/§2.10/§3.2–§3.7, 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (incl. pinned two-step rounding for mtm_rent_cents with the forbidden single-rounding variant named; provisional vs final pricing variants), 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (serve 3-link cascade, supersede cascade, revert check, countersign 3-record rewrite), 0 missing
- entities[].fields[] structured content: defaults/nullability/derived values reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (revert branches, rescind-restore branches, TRAILING/PIPELINE, pricing variants, ACCEPT/DECLINE/COUNTER, strategy factors), all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: all
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directories were inspected.

## Step 5: Generate unit tests — 2026-08-12T05:03:00.000Z

Done. Generated complete test infrastructure and suite for task_1232.

## What was built

**`test_helpers/`** (9 files): `types.py` (9 entity TypedDicts — all carry the full common-field set — plus 8 domain enums), `api_client.py` (41 endpoint methods matching PRD §4), `api_errors.py` (35 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity validators, including the §2.8 effective-cap invariant on policies), `factories.py` (input-only payload builders), `constants.py` (PRD thresholds: MTM premium 1500, term-discount 10/180, concession tiers 300/800/2000, CA-OAK fixture), `test_users.py` (opaque staff headers `user_la_1`/`user_pm_1`/`user_pm_2`/`user_la_2`/`user_rd_1`/admin + mandatory `make_resident_headers()` for the entity-backed Resident role), `fixtures.py` (tiered composites: hierarchy, issued/countered/accepted/executed offer chains, notice serve, clock advance, document lookup), `__init__.py` barrel.

**`test_suite/`**: `conftest.py` + 8 test files, **86 tests**, collected cleanly by pytest.

## Coverage audit results
- **Queue A (difficulty)**: 17 of 18 instances × 2 tests each = 34 tests.
- **Queue B (corner)**: all 43 non-stub instances × 1 test = 52 tests. All 9 `excluded_because:` stubs verified to resolve to real difficulty instances and were not translated.
- Every test carries exactly one `Design: Difficulty/...` or `Design: Corner/...` tag resolving to a real instance; no untagged, dual-tagged, or dangling tags.
- All 120 quoted PRD citations (≥8 words) survive a literal grep of `workspace/PRD.md` (four elided/punctuated quotes were found and fixed).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments.

## One deliberate gap (PRD-first filter)
`Difficulty/cross_entity_state_dependency/offer_create_blocked_when_lease_noticed` was **skipped**: the PRD names `ERR_LEASE_NOT_ISSUABLE` only for offer *issue* (§3.4) and notice *serve* (§3.6); §3.3 states no lease-state precondition for offer *creation*, so a PRD-only implementer could legitimately allow creating an offer against a NON_RENEWAL_NOTICED lease. The asserted create-time rejection is not uniquely derivable, so no test was emitted (no placeholder, no weakening). This is a PRD coverage gap worth flagging upstream.

## Notes on judgment calls
- `expiration_forecast_counts`: the PRD pins `window_start`/`months` and the "committed"/"projected" count names but not the month-date string format; the test compares month keys by `YYYY-MM` prefix while asserting the exact committed/projected counts.
- `version == 1`-at-creation assertions (3 corner instances) were kept per the pre-audited design literals; §2.5's increment rule plus the OCC flows make 1 the canonical reading.

## Step 6: Generate implementation — 2026-08-12T05:03:00.000Z

Implementation complete. Final report:

## Implementation Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1232_lease_renewal_rent_increase_administration/workspace/implementation/`:

### File layout
- `start.sh` — executable, guarded dependency install (skips `pip install` when flask already importable), `exec python3 app.py` in foreground
- `requirements.txt` — flask only
- `app.py` — Flask factory, blueprint registration, error handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `store` singleton with dicts per entity; logical clock starts at `2026-05-01T00:00:00Z`
- `errors.py` — `ApiError` class + full error catalog with exact IDs and HTTP statuses from SCAFFOLD §1.6
- `response.py` — envelope helpers producing `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, and list pagination fields `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, five declared roles, role gating per endpoint
- `timeutil.py` — `parse_date`, `add_months` (day-preserving, clamped), `parse_instant`, logical-clock accessors, quarter/month bucketing
- `services/common.py` — `new_entity`, `touch` (version bump + `updated_at` refresh)
- `services/calc.py` — all calculations: `effective_cap_bps`, six-step `compute_pricing` (provisional + final variant via parameter selection), `notice_days_required` (strict `>` threshold), `latest_issue_date` (None for MTM), `staggered_term_selection` (load-minimizing with larger-t tiebreak), `mtm_rent_cents` (two pinned rounding steps), `concession_bps_for`, `compute_retention_metrics` (TRAILING vs PIPELINE), `compute_expiration_forecast`
- `services/lifecycle.py` — `lease_revert_check`, `withdraw_offer_cascade`, `void_pending_concessions_for_offer`, and the four-step `sweep` (cure-lapse → enforcement → offer expiry/void → MTM conversion)
- `routes/` — ten blueprints, one per resource group; all 41 endpoints from SCAFFOLD §1.5 registered (verified via `app.url_map.iter_rules()`)

### Verified behaviors via live smoke tests
- Fresh boot via `bash start.sh` on `$PORT` returns 200 with empty store
- Full lifecycle: policy → property → unit → resident → lease → offer (OCC `expected_lease_version`, staggered term picking 24mo when 12/24 tied) → issue → accept (auto-creates RenewalDocument) → sign → countersign (final-variant recompute, lease renewed with `term_start = max(old_term_end, clock)`, version bump)
- Clock sweep MTM conversion: lease past `term_end_date` transitions to MTM with two-step rounded rent (`200000 × 1.04 = 208000`, then `208000 × 1.15 = 239200`), `mtm_converted_on` set, `transitions_applied` counted
- Envelope shape confirmed: separate `meta`/`response_type`/`data` for both success and error responses; pagination fields only on list responses

### Constraints honored
- No seeding at startup — store is empty on each fresh process
- All storage in Python dicts; no SQLite, no files
- `start.sh` reads `$PORT`, binds `0.0.0.0`, runs foreground via `exec`
- Did not read SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, test_helpers/, or any sibling task directory
- Only the 41 declared (method, path) route pairs are registered

### Orchestrator route parity check (independent verification)
`app.url_map.iter_rules()` vs SCAFFOLD.yaml §1.5, placeholders normalized: scaffold 41, impl 41 non-static — MISSING: none, EXTRA: none. All 41 (method, path) pairs registered.

## Step 7: Run tests and iterate — 2026-08-12T05:13:00.000Z

Clean 8-round parallel sweep achieved: all rounds 86/86 passed.

## Summary

- **Iterations run**: 2 sweeps (round 1: 85/86 in all 8 rounds; round 2: 86/86 in all 8 rounds).

- **Tests deleted**: none. Every assertion in the suite traces to verbatim PRD prose; the single failing test survived both STEP 1 sub-checks (PRD §2.9's numbered validation pipeline verbatim fixes temporal-window stage 9 before domain-constraint stage 10(a), and that ordering is uniquely derivable).

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`** (both in the validation-pipeline ordering, PRD §2.9 "the first failing stage wins"):
  1. `/home/ubuntu/github/CodingPRD/tasks/task_1232_lease_renewal_rent_increase_administration/workspace/implementation/routes/offers.py` — `revise_offer`: reordered checks so the statutory rent cap (stage 8, `ERR_RENT_CAP_EXCEEDED`) and the high-tier notice-window check (stage 9, `ERR_NOTICE_WINDOW_MISSED`) run BEFORE the staggering-band check (stage 10a, `ERR_TERM_OUTSIDE_STAGGERING_BAND`) and the approved-concession gate (stage 10h, `ERR_CONCESSION_APPROVAL_REQUIRED`). Previously the term-band check fired first, which made `test_temporal_beats_term_band_on_revise_error` see `ERR_TERM_OUTSIDE_STAGGERING_BAND` instead of the earlier-stage `ERR_NOTICE_WINDOW_MISSED`.
  2. `/home/ubuntu/github/CodingPRD/tasks/task_1232_lease_renewal_rent_increase_administration/workspace/implementation/routes/notices.py` — `serve_notice`: moved the segregation-of-duties check (stage 10e, `ERR_SEGREGATION_OF_DUTIES`) ahead of the repositioning quarterly quota check (stage 10g, `ERR_REPOSITIONING_QUOTA_EXCEEDED`) to match PRD §2.9's fixed stage-10 sub-order (e before g). No failing test exercised this conflict; fixed proactively for PRD fidelity.

Final state: 8/8 parallel rounds, each 86/86 passed, zero flakiness observed across the union of rounds. Orchestrator independently verified `results.1..8.json` all report passed=86 total=86 failed=0.

## Step 8: Finalize PRD — 2026-08-12T05:15:00.000Z

All enumerated paths are consistent with PRD §2.9 verbatim — including the sibling paths (`issue_offer` at offers.py:233, resident counter term-band at offers.py:290, concession approve/deny SoD at concessions.py:128/152), none of which co-occur with the reordered checks in a way the PRD leaves open. The "no edit" decision holds.

## Summary

**PRD_FINALIZED.md produced** at `/home/ubuntu/github/CodingPRD/tasks/task_1232_lease_renewal_rent_increase_administration/workspace/PRD_FINALIZED.md` — a byte-identical copy of PRD.md (verified with `diff -q`).

**Line counts / %-delta:** PRD.md = 304 lines; PRD_FINALIZED.md = 304 lines; delta = 0 lines, 0.0%.

**Changes:** none — zero edits.

**Rationale:** Both `<step_7_diff>` items were implementation fixes that brought code *into* alignment with behavior PRD §2.9 already uniquely pins, so there was no PRD-silence or PRD-mismatch to patch:

- **§2.9 (stages 8/9 vs 10a/10h) — no edit — impl aligned to existing verbatim prose** — PRD §2.9's numbered pipeline ("the first failing stage wins... drawn from the earliest stage that fails") lists stage 8 = statutory rent cap, stage 9 = statutory temporal windows, stage 10 = domain constraints in "fixed sub-order" (a)–(h). The fixed `revise_offer` (implementation/routes/offers.py:369-394) checks cap → notice window → term band → concession gate, exactly that order. Ordering was uniquely derivable; no PRD wording change needed.
- **§2.9 (stage 10 sub-order e vs g) — no edit — impl aligned to existing verbatim prose** — PRD §2.9 stage 10 says "evaluated in this fixed sub-order: ... (e) segregation of duties ... (g) the repositioning quarterly quota." The fixed `serve_notice` (implementation/routes/notices.py:160-181) runs SoD before quota, exactly that order. Uniquely derivable; no PRD wording change needed.

**Per-edit pre-edit search log** (mandatory (a)/(b) for each candidate edit; both candidates resolved to "no edit"):

1. **Candidate edit: revise_offer check ordering (cap/window vs term-band/concession-gate)**
   - (a) Subject: relative order of `ERR_RENT_CAP_EXCEEDED`, `ERR_NOTICE_WINDOW_MISSED`, `ERR_TERM_OUTSIDE_STAGGERING_BAND`, `ERR_CONCESSION_APPROVAL_REQUIRED`.
   - (b) Enumerated/read: implementation/routes/offers.py:331-418 (`revise_offer` — full read); grep across all `routes/*.py` for the four error codes — co-occurrence exists only in `revise_offer`; sibling single-check sites offers.py:233 (issue notice-window) and offers.py:290 (counter term-band) carry no cross-stage ordering. PRD.md §2.9 lines 110-121 read verbatim.
   - (c) Outcome: PRD already pins the order (stages 8, 9, then fixed 10 sub-order a→h); impl matches. No wording inserted — edit rejected as unnecessary.

2. **Candidate edit: serve_notice SoD vs repositioning quota ordering**
   - (a) Subject: relative order of `ERR_SEGREGATION_OF_DUTIES` (10e) and `ERR_REPOSITIONING_QUOTA_EXCEEDED` (10g).
   - (b) Enumerated/read: implementation/routes/notices.py:127-200 (`serve_notice` — full read); grep across all `routes/*.py` for both codes — quota raised only at notices.py:181; SoD also at concessions.py:128/152 (approve/deny), where no quota check co-occurs, so no competing order. PRD.md §2.9 line 121 read verbatim.
   - (c) Outcome: PRD's "fixed sub-order ... (e) ... (g)" already pins e before g; impl matches. No wording inserted — edit rejected as unnecessary.

Final state: a fresh implementer reading PRD_FINALIZED.md alone gets §2.9's explicit stage-8→9→10(a)–(h) pipeline with first-failing-stage-wins, which uniquely determines both behaviors step 7 fixed in code.

## Step 9: Complete PRD — 2026-08-12T05:29:00.000Z

All edits are in place and verified. Final summary:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (304 lines, 51,117 chars) → `PRD_COMPLETED.md` (306 lines, 55,929 chars), char-delta **+4,812**. All changes are inline inserts/revisions; no new sections, no reordered structure.

**Counts:** ~31 ambiguity-pins (insert), 3 mismatch-revisions (revise).

### Changes

- **§2.2** — insert — ambiguity — pinned framework-level errors: unknown route → `ERR_NOT_FOUND` (404), wrong method → `ERR_METHOD_NOT_ALLOWED` (405), unhandled failure → `ERR_INTERNAL` (500) — `implementation/app.py:30-42`.
- **§2.3** — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamp (limit→[1,100], offset→0) — `implementation/routes/properties.py:30-42`.
- **§2.3** — insert — ambiguity — defined `total_count` (pre-pagination filtered count) and `has_more` (`offset + returned < total_count`) — `implementation/response.py:20-34`.
- **§2.4** — insert — ambiguity — clock instant normalized to UTC whole seconds, stored as given (no monotonicity check), sweep compares UTC calendar dates only — `implementation/routes/clock.py:20-29`, `implementation/timeutil.py:38-42`.
- **§2.4** — insert — ambiguity — `transitions_applied` tallies every mutated entity, not each rule fired — `implementation/services/lifecycle.py:46-152`.
- **§2.5** — insert — ambiguity — `version` starts at 1; any successful update bumps `version`/`updated_at` even when no field changes — `implementation/services/common.py:8-20`.
- **§2.5** — insert — ambiguity — record/envelope timestamps read the wall clock; logical clock governs only domain dates — `implementation/db.py:11-14`.
- **§2.5** — insert — ambiguity — date input parsing accepts non-zero-padded numerals; emitted dates always `YYYY-MM-DD` — `implementation/timeutil.py:13-21`.
- **§2.7** — insert — ambiguity — absent/non-integer `expected_lease_version` → `ERR_INVALID_REQUEST` (not 412) — `implementation/routes/offers.py:107-109`.
- **§2.7** — **revise** — **mismatch** — property update takes an *optional* `expected_property_version` (PRD said "requires"); omitted → no OCC check; non-integer → `ERR_INVALID_REQUEST` — `implementation/routes/properties.py:124-130`.
- **§2.10** — insert — ambiguity — "open offer" globally means `DRAFT`/`ISSUED`/`COUNTERED`/`ACCEPTED` unless a narrower set is named — `implementation/services/calc.py:20`, `implementation/services/lifecycle.py:19-33`.
- **§3.1** (policy) — insert — ambiguity — PATCH accepts any subset of the seven numeric fields; creation-time non-negativity not re-enforced — `implementation/routes/policies.py:77-92`.
- **§3.1** (property) — **revise** — mismatch — consequential rewording: OCC write takes an "optional" expected version — `implementation/routes/properties.py:102-138`.
- **§3.1** (unit) — insert — ambiguity — `current_market_rent_cents` must be a non-negative integer — `implementation/routes/units.py:57-58`.
- **§3.2** — insert — ambiguity — lease `monthly_rent_cents` must be a non-negative integer — `implementation/routes/leases.py:78-79`.
- **§3.2** — insert — ambiguity — Resident lease list implicitly scoped to own leases before filters — `implementation/routes/leases.py:133-135`.
- **§3.3** — insert — ambiguity — offer creation requires lease `ACTIVE`/`MTM`/`RENEWAL_PENDING`, else `ERR_LEASE_NOT_ISSUABLE` — `implementation/routes/offers.py:117-119`.
- **§3.3** — insert — ambiguity — zero base rent ⇒ market gap defined as 0 bps — `implementation/services/calc.py:42-48`.
- **§3.3** — insert — ambiguity — `proposed_increase_bps` recomputed from rounded rent, half-up, floored at 0, zero when base is zero — `implementation/services/calc.py:75-82`.
- **§3.3** — insert — ambiguity — Resident offer list implicitly scoped to own lease — `implementation/routes/offers.py:188-191`.
- **§3.4** (issue) — insert — ambiguity — check order pinned: offer `DRAFT` state → lease issuable state → statutory window — `implementation/routes/offers.py:226-233`.
- **§3.4** (respond) — **revise** — **mismatch** — "records both counter fields" → `counter_term_months` recorded only when supplied, stays null otherwise — `implementation/routes/offers.py:320-325`.
- **§3.4** (revise) — insert — ambiguity — MTM leases exempt from the high-tier notice-window check — `implementation/routes/offers.py:373-379`.
- **§3.4** (revise) — insert — ambiguity — `issued_by_user_id` is not restamped on revise — `implementation/routes/offers.py:396-412`.
- **§3.5** — insert — ambiguity — `requested_rent_cents` must be a positive integer — `implementation/routes/concessions.py:57-58`.
- **§3.5** — insert — ambiguity — within the state stage, the `SUBMITTED` check fires before the linked-offer `COUNTERED` check — `implementation/routes/concessions.py:120-125`.
- **§3.6** (serve) — insert — ambiguity — effective-date validity fires before the lead-time check — `implementation/routes/notices.py:147-157`.
- **§3.6** (rescind) — insert — ambiguity — still-`SERVED` but past-cure rescind also → `ERR_NOTICE_NOT_SERVED`; neither serve nor rescind touches lease `status_before_offer` — `implementation/routes/notices.py:211-229, 191-198`.
- **§3.7** — insert — ambiguity — countersign's lease-`ENDED` guard returns `ERR_DOCUMENT_INVALID_STATE`, with the `RESIDENT_SIGNED` check first — `implementation/routes/documents.py:124-127`.
- **§3.7** — insert — ambiguity — Resident document list implicitly scoped to own lease — `implementation/routes/documents.py:65-68`.
- **§3.8** (retention) — insert — ambiguity — missing/malformed params or unknown `variant` → `ERR_INVALID_REQUEST` — `implementation/routes/properties.py:147-158`.
- **§3.8** (retention) — insert — ambiguity — cohort membership includes docs currently `COUNTERSIGNED` *or later `RESCINDED`*; defined `mtm_count` (cohort leases currently `MTM`) and `lost_count` (ENDED with no doc currently `COUNTERSIGNED`) — `implementation/services/calc.py:204-218, 266-271`.
- **§3.8** (forecast) — insert — ambiguity — `months_ahead` defaults 12, clamped to [1,60], non-integer → `ERR_INVALID_REQUEST`; response entries carry `month` (`YYYY-MM`), `committed`, `projected`; `window_start` is the first of the current clock month — `implementation/routes/properties.py:169-177`, `implementation/services/calc.py:302-340`.

Everything else in the implementation (sweep order and date-comparison strictness, pricing pipeline steps, staggering algorithm, supersede sets, tier limits, quota rule, snapshot/restoration semantics, role tables, error catalogue) matched existing PRD pins and required no change.
