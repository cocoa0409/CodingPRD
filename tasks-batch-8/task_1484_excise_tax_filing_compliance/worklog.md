# Worklog — task_1484_excise_tax_filing_compliance

## Step 1: Create Task Directory — 2026-08-13T12:14:00.000Z

Task directory `tasks/task_1484_excise_tax_filing_compliance/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T14:28:00.000Z

All three scaffold artifacts are written and lint-clean. Summary:

## Files written (all three, confirmed on disk)

- `/home/ubuntu/github/CodingPRD/tasks/task_1484_excise_tax_filing_compliance/SCAFFOLD.yaml` (§1.0–§1.7 only — no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1484_excise_tax_filing_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1484_excise_tax_filing_compliance/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

## Counts

- **Entities: 14** (Registrant, Jurisdiction, ProductClass, TaxRate, RateChangeNotice, Registration, Bond, ExemptionCertificate, BondedMovement, TaxableEvent, TaxReturn, Deposit, CreditClaim, AuditCase)
- **State machines: 12** (incl. cyclic re-rate/amendment loop on TaxableEvent, parallel filing×settlement dimensions on TaxReturn, resubmission loop on CreditClaim) + **2 OCC concurrency rules** (return filing, notice application)
- **Calculations: 11** (incl. three dual-variant domains: event determination, deposit schedule, bond requirement; per-event rounding pin; pinned evaluation-order settlement)
- **Endpoints: 77** (flat topology, FK-filtered lists for reverse reachability, one `/_clock/set_current_utc` test-driving endpoint with the mandated `2026-08-01T00:00:00Z` default)
- **Errors: 35** (all referenced by validations/transitions)
- **Validations: 35** ordered rows; **Roles: 5** with segregation-of-duties (preparer≠filer, claimant≠approver)
- **Difficulty instances (§1.8): 27 non-stub** — 3 per rule × 9 rules, each with fully structured `setup_api_calls`/`trigger`/`assert` and hand-computed literal expectations (e.g. 24.3¢ rounding → 72-not-73; 5-vs-6-day penalty 200/500; exactly-90% safe-harbor 0 vs 1000; STANDARD 1458000 vs AGGRAVATED 2500000 bond)
- **Corner instances (§1.9): 78 total, 66 non-stub, 12 `excluded_because` stubs** across all nine guide sections (entities 8, state_machines 13, calculations 9, validations 20, endpoints 5, rbac 7, cross-cutting layers 7, consistency 1, errors 8 stubs)

## Verification

- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (1276 calls scanned)
- Additional audits passed: instance-name uniqueness across both design files, every `grounds:` reference resolves to a declared §1.1–§1.7 element, every stub cites an existing §1.8 instance, no forbidden concurrency vocabulary, every error triggerable, enum closure.
- Fixes applied during iteration: locked-period fallback for system-created default-assessment events, claim-overlap check moved to submit-only, quarterly→monthly deposit constraint pinned, `applied_rate_id?` filter added for FK reachability, YAML quoting of bracketed grounds and indexed JSONPath captures.
- No sibling task directories were read at any point; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-13T14:29:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1484_excise_tax_filing_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T14:32:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1484_excise_tax_filing_compliance/workspace/PRD.md` (confirmed on disk)

**Line count:** 366 lines

**Section structure:**
- §1 Introduction (2 paragraphs — business context + design commitments)
- §2 Global Specifications (11 subsections): 2.1 RBAC, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination, 2.4 Logical Clock & Sweeps, 2.5 Common Resource Properties, 2.6 Money/Milli-Cent Rates/Rounding, 2.7 Period Keys & Validity Windows, 2.8 OCC, 2.9 Segregation of Duties, 2.10 Request Validation Order, 2.11 Registrant-Chain Scoping
- §3 Business Logic & Workflows (9 subsections, domain-derived: registrations/bonds, rate schedule, rate-change notices, taxable activity, certificates/movements, returns, deposits, claims, audit/retention)
- §4 Endpoint Definitions (77/77 endpoints, 4-column table only)
- §5 Error Code Catalogue (35/35 errors, 2-column table only, no trigger conditions)

**Coverage audit (scaffold §1.1–§1.7):**
- Contract 1 Field-Name Coverage: **PASS** — entities[].fields 92/92, endpoint inputs+filters 63/63, path params 1/1, zero missing
- Contract 2 Rule Coverage: **PASS** — validation priority order rendered as an explicit 16-step evaluation sequence in §2.10 covering all 35 scaffold rules in priority order; both OCC rules expressed with write operation + `expected_return_version`/`expected_jurisdiction_version` + `ERR_STALE_VERSION`/412; all 63 state transitions, all 11 calculations (including STANDARD vs DEFAULT_ASSESSMENT variants, SAFE_HARBOR vs ACTUAL, STANDARD vs AGGRAVATED bond variants, pinned 5-step settlement, tiered late-deposit penalty), all multi-link cascades (notice-apply 4-link, movement-default 3-link, revocation with cascade suppression), and all `applies_to` scopes (6-op registration-active, 5-op audit hold, 9-context cross-registrant) rendered in prose
- Contract 3 §3 Path Purity: **PASS** — 724 backticked tokens scanned in §3, zero path tokens, zero bare HTTP methods, zero method+path combos

**Zero-silence check:** all 35 error IDs, all 45 state values, all 66 enum values, and all 5 role names appear in prose; no pseudocode operators (`==`, `>=`, `min(`, `->`, etc.) anywhere in the document; document ends at §5 with no audit footer. The withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-13T14:47:00.000Z

Generation complete for task_1484_excise_tax_filing_compliance.

## Summary

**Total tests emitted: 120** (all class-scoped `def test_*(self, api)`, pytest-collectible, zero collection errors)

**Queue A (§1.8 difficulty, depth): 54 tests**
- All 27/27 instances covered with ≥2 tests each (each instance split into two facet tests, e.g. boundary-accepted vs boundary-rejected, cascade link 1 vs links 2–4, forward apply vs compensating reverse).

**Queue B (§1.9 corner, breadth): 66 tests**
- All 66/66 non-stub instances covered with exactly 1 test each.
- 12 `excluded_because:` stubs not translated (1 validations priority stub, 3 cross-cutting stubs, 8 error stubs); all 12 `difficulty_instance` cross-references verified to resolve to real §1.8 names.

**Instances skipped: 0** — every non-stub instance passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability). No placeholder/skip/xfail tests exist.

**Two PRD-adjudication notes:**
1. `claim_apply_reverse_conserves_return_credit_ledger`'s mid-state yaml value (`net_due == 2440`) contradicts the PRD's pinned settlement order (24300 tax − 24300 credits + 2430 underpayment penalty = **2430**); the test asserts the PRD-derived 2430.
2. `taxable_events_list_pagination_envelope`: all events share one logical-clock `created_at`, and the PRD pins no tie-break — the test asserts page size/total_count/has_more and exact page membership, not intra-tie order.

**test_helpers/ written (9 files):** `__init__.py` (barrel), `types.py` (14 entity TypedDicts + 19 enums), `api_client.py` (one method per endpoint, ~60 methods), `api_errors.py` (35 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity + invariant checkers), `factories.py`, `constants.py` (floors, tiers, caps, retention), `test_users.py` (4 opaque roles + per-user builders), `fixtures.py` (composite helpers: active-registration chain, rated/filed return lifecycles, amendment opening, claim submit→apply chains, dispatched movements, verified certificates, audit cases, validated notices — all with fresh per-call X-User-IDs to keep SoD deterministic, and uuid-suffixed codes/feins for uniqueness).

**test_suite/ written (11 files):** `conftest.py` (session api + role fixtures) + `test_01_taxonomy_envelope_pagination.py`, `test_02_registrations_bonds_retention.py`, `test_03_certificates_movements.py`, `test_04_rates_notices.py`, `test_05_events_returns_amendments.py`, `test_06_deposits_settlement.py`, `test_07_credit_claims.py`, `test_08_audit_cases.py`, `test_09_rbac_occ_priorities.py`, `test_10_cross_entity_variants.py`.

**Stage 2 self-audit verdict: PASS**
- Tag coverage: 120/120 tests carry exactly one `Design:` tag as the docstring's final line; 54 tagged `Difficulty/<rule_id>/<name>`, 66 tagged `Corner/<section>/<name>`; 0 untagged, 0 dual-tagged, 0 tags resolving to non-existent instances, 0 tags pointing at stubs.
- Citation pass: 179 quoted PRD fragments extracted from docstrings all survive literal grep of PRD.md (whitespace-normalized); initial sweep caught 21 ellipsis-bridged quotes, all rewritten to contiguous verbatim sentences and re-verified.
- No scaffold references in generated code; no `pytest.mark.skip`/`skipif`/`xfail`; suite collects cleanly under the runner's PYTHONPATH.

## Step 6: Generate Implementation — 2026-08-13T14:47:00.000Z

Implementation complete. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1484_excise_tax_filing_compliance/workspace/implementation/`:

- `start.sh` — executable; guards `pip install` behind a `python3 -c "import flask"` check (no-op on per-test reboots), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry: blueprint registration, auth `before_request` gate, envelope error handlers (404/405 → `ERR_NOT_FOUND` envelope), binds `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dicts for all 14 entities + logical clock (starts exactly `2026-08-01T00:00:00Z`); empty at every boot, no seeding anywhere
- `utiltime.py` — ISO-8601 3-fractional-digit formatting/parsing, period-key arithmetic (YYYY-MM / YYYY-Qn), month buckets, `Decimal` ROUND_HALF_UP helpers
- `errors.py` — all 35 catalog error IDs with their HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data{error_id, message}`
- `auth.py` — `X-User-ID`/`X-User-Role` validation, role gating, strict body validators, pagination (limit default 10, clamped to [1,100]; offset default 0), common-field entity factory, change-detecting `touch_if_changed` (recompute = mutation)
- `services.py` — all calculations, cascades, and the daily sweep
- `routes/config.py` — clock, jurisdictions, product-classes, tax-rates, rate-change-notices
- `routes/registrants.py` — registrants, registrations (activate/suspend/reinstate/revoke/bond-status/purge), bonds
- `routes/compliance.py` — exemption-certificates, bonded-movements
- `routes/events.py` — taxable-events (classify/rate/reclassify/void)
- `routes/returns.py` — returns (submit/withdraw/file/amend/summary), deposits (pay/waive)
- `routes/claims.py` — credit-claims (submit/approve/deny/apply/reverse/withdraw/resubmit)
- `routes/audit.py` — audit-cases (request-documents/begin-review/close)

## Coverage

- **Endpoints: all 77** from the scaffold endpoint table (verified against the Flask route map).
- **State machines: 11** — Registrant, Registration, Bond, ExemptionCertificate, BondedMovement, TaxableEvent, TaxReturn (dual filing/settlement dimensions), Deposit, CreditClaim, AuditCase, RateChangeNotice + TaxRate informational status derivation.
- **Calculations: all 11** — event_tax_determination (STANDARD + punitive DEFAULT_ASSESSMENT 1.5×max-rate variant), rate_window_resolution (half-open, status-agnostic), return_liability_aggregation (per-event pinned rounding, never re-rounded), deposit_schedule (SAFE_HARBOR 0.5×prior/floor-10000 + ACTUAL window-close sweep), late_deposit_penalty (2%/5% tiers, 16+ days → 10% + 0.05%/day, per-component rounding), return_settlement (pinned 5-step waterfall with deposit ordering due_date→created_at, excess→overpayment, 90% underpayment + 5%/started-30-day-month capped at 25%), export/bad-debt eligibility (183/731-day windows, CLAIM_CAP 5,000,000), bond_requirement (STANDARD 3×/6-mo/$10k floor vs AGGRAVATED 5×/12-mo/$25k floor on trailing-12-month defaults/reversals), registrant_liability_rollup, retention_eligibility (7-year anchor).
- **Concurrency**: OCC on return file (`expected_return_version`) and notice apply (`expected_jurisdiction_version`) → `ERR_STALE_VERSION` 412; SoD on file/approve/deny → 403; validation priority per PRD §2.10.

## Boot verification

`bash start.sh` boots cleanly on a fresh process twice in a row (HTTP 200 each time, empty store, clock at `2026-08-01T00:00:00.000Z`). Two throwaway end-to-end suites (run against live servers on ports 18341–18344, all killed afterward) passed 100%: ~90 checks covering the full pipeline — auth/RBAC, envelope shape, rating math (24300 millicents × 100 units = 2430¢), exemption/suspension zero-tax, deposit schedules and safe-harbor amounts, the filing waterfall with overpayment (7570¢ excess), amendment carry-forward and parent supersession, rate-notice apply with window clamping + retro re-rate + jurisdiction version bump, clock-sweep transitions (rate activation, movement timeout default with punitive 1800¢ assessment, ACTUAL window close, deposit LATE marking, 30-day bond-deficiency registrant suspension and recovery), audit records-hold blocking claim apply, credit claim approve/apply/reverse with settlement flips and overpayment accounting, bad-debt timing windows, tier-3 late penalty (134¢ on 1215¢ at 20 days), pagination meta, and retention gating. One bug was found and fixed during testing (`period_open_target` treated a never-created period as locked); the final tree passes both suites clean.

## Step 7: Run Tests and Iterate — 2026-08-13T14:58:00.000Z

All 8 rounds passed 120/120. Let me emit the summary.

## Summary

- **Iterations run**: 2 (initial sweep + post-fix sweep, 8 parallel rounds each)
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**:
  - `fixtures.py`: added missing `make_reviewer_headers` import (was referenced at line 56 but not imported) — root cause for 52 of 67 initial failures.
  - `fixtures.py`: added `_EVENT_KWARGS` router in `setup_return_with_rated_event` so test call sites may pass event fields like `quantity_units` directly (they get routed into `event_overrides`) — root cause for 5 setup TypeErrors.
- **Fixes applied to `test_suite/`**:
  - `test_03_certificates_movements.py::test_certificate_one_day_gap_accepted`: shifted `valid_from` from `2026-07-01` to `2026-07-02` so the windows actually have a one-day gap (PRD §3.5 "windows that touch or overlap are rejected"; 6-30 → 7-01 are adjacent/touching and must be rejected).
  - `test_06_deposits_settlement.py::test_late_filing_penalty_stacked_with_underpayment`: corrected `net_due_cents` from 27940 → 27945 (= 24300 tax + 3645 penalties, per PRD §3.6 step five).
  - `test_06_deposits_settlement.py::test_filing_response_reflects_final_state_immediately`: corrected `net_due_cents` from 26740 → 26730 (= 24300 tax + 2430 underpayment penalty).
  - `test_06_deposits_settlement.py`: added missing `setup_filed_return` import.
  - `test_06_deposits_settlement.py`: threaded the `api` fixture into `_setup_overpaid_deposit` and `_rate_and_pay` helpers (they referenced `api` as a free variable).
  - `test_07_credit_claims.py::TestDeniedResubmitLoop._setup_denied_claim`: threaded `api` fixture into the helper (same pattern).
  - `test_07_credit_claims.py::test_claim_apply_then_full_reverse_restores_net_due`: corrected `net_due_cents` invariant from 26740 → 26730 (same arithmetic correction).
- **Fixes applied to `implementation/`**:
  - `services.py::run_default_cascade`: set the auto-spawned `DEFAULT_ASSESSMENT` event's `bonded_movement_id` to the originating movement's id (was `None`). PRD §3.5 ties the spawned event to the defaulted movement, and `list_taxable_events(bonded_movement_id=...)` must surface it.

Final state: 120/120 passing in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-08-13T15:02:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one inline revision.

## Summary

**Line counts**: PRD.md 366 lines, PRD_FINALIZED.md 366 lines (one line modified in place; 0.0% line-count delta, single-sentence revision).

### Changes
- **§3.5 (Exemption Certificates and Bonded Movements)** — revise — In the default-assessment cascade's first link, added "its `bonded_movement_id` naming the defaulted movement" to the sentence describing the auto-created `DEFAULT_ASSESSMENT` event — impl: `/home/ubuntu/github/CodingPRD/tasks/task_1484_excise_tax_filing_compliance/workspace/implementation/services.py:646` (`run_default_cascade`).

### Items evaluated with no PRD change needed
- `fixtures.py` `make_reviewer_headers` import + `_EVENT_KWARGS` router — pure test-fixture plumbing bugs; no behavioral content.
- `test_03` certificate one-day-gap shift — test was wrong; PRD §3.5 already pins impl behavior ("gap of at least one day … windows that touch or overlap are rejected"; impl rejects when `valid_from <= existing.valid_to + 1 day` at `implementation/routes/compliance.py:64`, so 06-30 → 07-01 touches and is rejected, 07-02 leaves one full uncovered day and is accepted).
- `test_06`/`test_07` `net_due_cents` corrections (27940→27945, 26740→26730 ×2) — test arithmetic errors; PRD §3.6 steps four/five already pin the formulas exactly (impl `services.py:556-575`: underpayment = rhu(0.10 × (taxable − deposits_applied)) = 2430, late = rhu(0.05 × 24300) = 1215, net = tax − credits − deposits + penalties).
- `test_06`/`test_07` import and `api`-fixture threading fixes — pure test bugs.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)
**Edit 1 — §3.5 cascade first link**
- (a) Subject: the default-cascade spawned event's `bonded_movement_id` linkage.
- (b) Impl paths enumerated and read:
  - `implementation/services.py:626-672` — `run_default_cascade` creates the event with `"bonded_movement_id": movement["id"]` (line 646), product class from the movement, registration/jurisdiction from the movement's registration.
  - `implementation/services.py:719` — clock-sweep auto-default calls `run_default_cascade` → identical linkage.
  - `implementation/routes/compliance.py:249-268` — manual `POST /bonded-movements/{id}/default` calls `run_default_cascade` → identical linkage.
  - `implementation/routes/registrants.py:208-215` — registration-revoke path sets movements `DEFAULTED` with the cascade suppressed; no event is created, so the linkage claim does not apply there — wording stays scoped inside the cascade sentence, consistent.
  - `implementation/routes/events.py:84-88` — event list filter `bonded_movement_id` does exact-equality matching, so the spawned event surfaces under that filter (consistent with §3.4's existing filter list, unchanged).
  - `implementation/routes/events.py:59, 167, 228` — event create (None), rate (set from body), reclassify (cleared to None; already covered by §3.4's "clearing its exemption and movement links") — none conflict.
  - `implementation/services.py:432` (`compute_event_tax`) — treats any linked event as suspension-relief during notice re-rates; the edit makes no claim about re-rate outcomes, so no conflict.
- (c) Wording adjustment: phrased as a bare factual clause ("its `bonded_movement_id` naming the defaulted movement") with no universal claims about filtering, re-rating, or the revoke path, keeping every enumerated path consistent.

## Step 9: Complete PRD — 2026-08-13T15:12:00.000Z

All edits landed. Verification: 26 diff hunks, all within existing paragraphs — no new sections. Final summary:

## Report

**Source:** `PRD_FINALIZED.md` (366 lines, 68,439 chars) → `PRD_COMPLETED.md` (368 lines, 71,969 chars). Char delta: **+3,530** (insert-only growth; the only deletions are the two mismatch sentences replaced inline).

**Counts:** 22 ambiguity-pins, 6 mismatch-revisions (28 logical changes across 26 diff hunks).

### Mismatch revisions (PRD described behavior impl does not exhibit)
- §2.5 — revise — mismatch — recomputation now counts as a mutation (version bump/`updated_at` refresh) only when a computed value actually changes — `implementation/auth.py:181-190` (`touch_if_changed`)
- §3.4 — revise — mismatch — dropped undefined "or the class is exempt-eligible" clause; classification's taxable-identified test is purely rate existence now-or-historically, superseded windows counting as historical — `implementation/services.py:60-64`
- §3.5 — revise — mismatch — receipt quantity bound split: above shipped → `ERR_MOVEMENT_QUANTITY_EXCEEDS`, negative → `ERR_INVALID_REQUEST` (PRD had pinned one error for both ends) — `implementation/routes/compliance.py:217,222-224`
- §3.7 — revise — mismatch — "Every return carries a deposit schedule" → every *original* return; amendments carry none — `implementation/services.py:272-284`
- §3.8 — revise — mismatch — deleted the "claim's amount is allocated to its eligible events in event_date/created_at order" record-keeping sentence; impl performs no allocation — `implementation/routes/claims.py:93-136`
- §3.8 — revise — mismatch — check order on submit pinned as already-claimed before export-documentation (PRD prose had export first) — `implementation/routes/claims.py:115-125`

### Ambiguity pins (PRD silent; pinned to impl)
- §2.2 — insert — ambiguity — unknown path / unsupported method → `ERR_NOT_FOUND` (404) in the standard error envelope — `implementation/app.py:41-48`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamped (limit→[1,100], offset→0); all list orderings break `created_at` (and deposit `due_date`) ties by insertion order — `implementation/auth.py:131-158`, `implementation/routes/returns.py:248-251`
- §2.4 — insert — ambiguity — every server-generated timestamp (envelope meta, `created_at`/`updated_at`, `detected_at`, `dispatched_at`, `paid_at`, `filed_at`) comes from the logical clock; clock advance rejects backward targets with `ERR_INVALID_REQUEST` — `implementation/response.py:17`, `implementation/utiltime.py:23-24`, `implementation/routes/config.py:49-50`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — `implementation/auth.py:168`
- §2.6 — insert — ambiguity — zero milli-cent rates permitted; negative rates malformed — `implementation/routes/config.py:124,185`
- §3.1 — insert — ambiguity — `registration_number` sequence is a per-jurisdiction counter starting at 1 — `implementation/routes/registrants.py:131-134`
- §3.1 — revise — ambiguity — revocation allowed only from `ACTIVE`/`SUSPENDED`; certificate/movement cascade applies from both; records-hold check scoped to `ACTIVE` only — `implementation/routes/registrants.py:183-218`
- §3.1 — insert — ambiguity — registrant auto-`CANCELLED` requires at least one registration to exist — `implementation/services.py:170-178`
- §3.1 — insert — ambiguity — bond-position read recomputes coverage/requirement on the fly (may mutate per §2.5) — `implementation/routes/registrants.py:225-237`
- §3.2 — insert — ambiguity — rate-window overlap check disregards `SUPERSEDED` windows — `implementation/routes/config.py:132-139`
- §3.3 — insert — ambiguity — notice application when no window contains the announced start: `supersedes_rate_id` null, `effective_to` = next later window's start or null; fully covered windows collapse to zero-width `SUPERSEDED` — `implementation/routes/config.py:278-299`
- §3.4 — insert — ambiguity — certificate coverage additionally requires the certificate to belong to the event's registration — `implementation/routes/events.py:141-145`
- §3.4 — insert — ambiguity — a `RATED` event with `return_id` null (locked-period default assessment) may be sent back for correction — `implementation/routes/events.py:199-204`
- §3.5 — insert — ambiguity — certificate gap arithmetic: new window must start strictly more than one day after the other's `valid_to` (or end strictly more than one day before its `valid_from`); exactly-one-day start rejected as touching — `implementation/routes/compliance.py:54-66`
- §3.5 — insert — ambiguity — `transit_deadline_days` minimum 1; bond status not checked at movement creation — `implementation/routes/compliance.py:141-150`
- §3.5 — insert — ambiguity — defaulting a fully received movement fails `ERR_INVALID_STATE` — `implementation/routes/compliance.py:256-259`
- §3.5 — insert — ambiguity — jurisdiction with no rates at all → punitive rate zero, assessment computes to zero tax — `implementation/services.py:449-454`
- §3.6 — insert — ambiguity — deposit waterfall ordering gains insertion-order tie-break after `due_date`/`created_at` — `implementation/services.py:541`
- §3.6 — insert — ambiguity — `pinned_rate_snapshot` carries one entry per taxed class: the rate of that class's earliest included event (event_date, created_at, insertion order), entries ordered accordingly — `implementation/services.py:584-602`
- §3.6 — insert — ambiguity — `add_event_ids` events attach to the amendment regardless of current status or prior return membership — `implementation/routes/returns.py:222-224`
- §3.7 — insert — ambiguity — ACTUAL recompute touches only `SCHEDULED`/`LATE` deposits; `PAID`/`APPLIED`/`WAIVED` keep their scheduled amount — `implementation/services.py:316-321,728-741`
- §3.8 — insert — ambiguity — 183/731-day claim windows measured calendar-date (filing date) to calendar-date (current logical date) — `implementation/routes/claims.py:105-112`

**Deliberately left unchanged** (PRD already adequate): the `System` role's 403 path (§2.1 uniform rule covers it); jurisdiction-consistency checks limited to events and claims (§2.11's exhaustive "Two tighter alignment rules" forecloses others, matching impl's unchecked return/audit-case jurisdiction fields); rate re-rate cascade skipping unattached `RATED` events (§3.3's "containing return" condition); sweep transition inventory (§2.4 matches `run_sweep` semantics; internal sweep ordering is unobservable between clock advances).
