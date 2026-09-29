# Worklog — task_2371_research_security_foreign_influence_disclosure

## Step 1: Create task directory — 2026-09-02T04:37:27.274Z

Created `tasks/task_2371_research_security_foreign_influence_disclosure/` and `tasks/task_2371_research_security_foreign_influence_disclosure/workspace/` (directory name was pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:17:22.179Z

Generation is complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2371_research_security_foreign_influence_disclosure/`, built only from the verbatim scenario text plus the scaffold-generator specification (no sibling task under `tasks/` was listed, read, or grepped).

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2371_research_security_foreign_influence_disclosure/SCAFFOLD.yaml` — 2,563 lines, §1.0–§1.7 only (contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,983 lines, single top-level key `scaffold_difficulty_design`
- `.../SCAFFOLD_CORNER_DESIGN.yaml` — 3,922 lines, single top-level key `scaffold_corner_design`

## SCAFFOLD.yaml counts (difficulty_level: `expert_plus`)

12 entities · 11 state machines (2 of them on `Project`, as parallel award/security dimensions) · 3 concurrency rules · 14 calculations · 20 validations in a strict priority ladder P1–P20 · 56 endpoints · 67 errors · 5 roles. Complexity profile: layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`, `entity_topology: graph`, `state_machine_shape: cyclic` (+ parallel/branching/posture_driven/guarded), `role_model: segregation_of_duties`, `consistency_model: immediate`.

## §1.8 depth probe — 21 instances across all 9 difficulty rules

`dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 3 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 2 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 2 (minimum of 2 per rule satisfied).

## §1.9 breadth probe — 90 instances (67 full recipes + 23 `excluded_because` stubs)

entities 13 · state_machines 11+4 · calculations 9+5 · validations 8+2 · endpoints 7 · errors 12+8 · rbac 3 · cross-cutting layers 3+4 · consistency_model 1.

## Coverage audit

- **Errors: 67/67 triggerable** — every catalog id is either raised by a full §1.9 recipe or explicitly delegated to a named §1.8 instance via `excluded_because`. Notable multi-error recipes: a 12-call sweep proving each entity family owns its own 404 code; incident notification guards (`ERR_NOT_INCIDENT_LEAD` → `ERR_SEGREGATION_OF_DUTIES` → `ERR_INVALID_NOTIFICATION_DATE` → success); plan guards (`ERR_PLAN_NOT_WARRANTED` → `ERR_PLAN_NOT_RESOLVED` → `ERR_SEGREGATION_OF_DUTIES` → `ERR_INVALID_PLAN_WINDOW`); closure guards (`ERR_ACCESS_GRANTS_OPEN` then `ERR_OPEN_INCIDENTS`).
- **Endpoints: 56/56 exercised** by at least one `call:` across the two design files (including all nine collection-list endpoints and the `/_clock/set_current_utc` test hook).
- **Entities: 12/12** referenced; all three §1.2.1 concurrency rules have a stale-version test (grant-create in §1.8, disclosure-create and organization-designate in §1.9's `optimistic_concurrency` layer).

## Lint verdict (pasted verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2371_research_security_foreign_influence_disclosure/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2371_research_security_foreign_influence_disclosure/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2371_research_security_foreign_influence_disclosure/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     12
  §1.8 instances scanned:     21
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  920

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two violations surfaced on the first run (rule (e): literal `expected_investigator_version: 1` and `expected_project_version: 1`); both were converted to GET-captured `${var}` values per the GET-before-OCC convention, after which the run above is clean. Instance names are unique across the union of both design files, and no name collides with a §1.8 instance referenced by a stub.

## Step 3: Copy shared files — 2026-09-02T06:17:22.179Z

Copied `INSTRUCTION.md` → `tasks/task_2371_research_security_foreign_influence_disclosure/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:37:17.777Z

PRD complete at `/home/ubuntu/github/CodingPRD/tasks/task_2371_research_security_foreign_influence_disclosure/workspace/PRD.md`.

## Document shape

- **464 lines**, 5 top-level sections, ends at §5 with no audit footer.
- **§1 Introduction** — 3 paragraphs (sponsor-pressure framing, scope, the two design commitments: synchronous derived-state reconciliation and segregated duties).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (5 roles, identity translation, ownership/assignment/SoD errors), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock, 2.5 Record Identity & `version` bookkeeping, 2.6 Effort/score rounding discipline, 2.7 Stale-view protection (3 OCC rules), 2.8 Path resolution + the full 20-step rejection order, 2.9 Cascade discipline, 2.10 Restricted-entity ownership graph, 2.11 Investigator/project postures and what they gate.
- **§3 Business Logic** — 9 subsections: onboarding + ownership graph; awards/roster/effort ledger; disclosure drafting & submission; officer review, completeness, certification & management plans; support-statement reconciliation; subaward screening + project security dimension; travel & controlled-area access; incident investigation/notification/closure; training, activation readiness & award closure.
- **§4** endpoint table (exactly 4 columns), **§5** error table (exactly 2 columns).

## Scaffold coverage

| Scaffold element | Count | Covered |
|---|---|---|
| Entities | 12 | 12 |
| State machines (incl. both Project and both Disclosure dimensions) | 11 | 11 |
| Calculations | 14 | 14 |
| Concurrency rules | 3 | 3 (§2.7) |
| Validations | 20 | 20 (§2.8, in priority order with per-rule scope) |
| Endpoints | 56 | 56 (§4) |
| Errors | 67 | 67 (§5, plus every ID used in prose) |
| Roles | 5 | 5 |

## Zero-Silence / Hard Contract audits (mechanical, scripted)

1. **Field-Name Coverage — PASS.** 149 required identifiers (127 entity fields incl. `id`/`created_at`/`updated_at`/`version` on all 12 entities, 72 request-body names, 23 query params, 12 path params, deduped) — 0 missing from PRD backticks.
2. **Rule Coverage — PASS.** All 67 error IDs present; all enum members from every entity enum field present (0 missing); every numeric/string/list constant value across all 14 calculations appears literally in the prose (0 missing — including `2,080`, `160`, `50`, `8`, the `CN`/`RU`/`IR`/`KP` list, type-point tables 20/40/15/35/30, notification windows 60/30/10/5, band floors 20/40/60, `PRIOR_INCIDENT_CAP` 20). All declared transitions are covered; 15 are expressed as grouped prose rather than the literal `A → B` string (the five Subaward `→ TERMINATED` sources enumerated in one sentence, the five SupportStatement transitions, the four `→ SUPERSEDED` disclosure sources, and `SUBSTANTIATED → AGENCY_NOTIFIED` described via the notify capability). Constant *names* are deliberately absent — translated to natural-language prose per the no-pseudocode rule.
3. **§3 Path Purity — PASS.** §3 spans lines 172–323; 0 `/`-prefixed tokens (in or out of backticks), 0 bare HTTP method tokens, 0 method+path combos.

Also verified: no fuzzy/approximating vocabulary, no scaffold-internal references (`§1.x`, `concurrency_rules[...]`) leaked into prose, and no sentinel markers remain.

Two scaffold-internal inconsistencies were resolved by explicit editorial decision and applied consistently: `ERR_DUPLICATE_DISCLOSURE_CYCLE` vs. the declared `CERTIFIED → SUPERSEDED` transition (CERTIFIED/REJECTED for a pair rejects the create; the four in-flight states supersede; `CERTIFIED → SUPERSEDED` described conditionally), and the training gates (stated as satisfied by `COMPLETED` **or** `WAIVED`, matching the waive endpoint's "a waiver satisfies the same gates"). Neither withheld design file was opened, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T07:17:25.655Z

The suite is complete and audits clean.

## Files written

**Stage 1 — `test_helpers/`** (9 files): `types.py` (5 roles, 40 enums, 12 TypedDicts all carrying `id/created_at/updated_at/version`), `api_client.py` (`ApiClient` with one method per documented endpoint, 56 total, plus the `api_client` singleton), `api_errors.py` (`ApiErrorId` with all 67 error ids + `HTTP_STATUS_CODES` registered with the framework via `set_error_http_status_map`), `constants.py` (published thresholds/weights/blocker order/pagination), `test_users.py` (role headers, two distinct identities per officer role for segregation-of-duties, `make_investigator_headers`), `factories.py` (13 payload factories, unique-email generator), `assertions.py` (12 per-entity assertions + invariant checkers), `fixtures.py` (~70 tier-1→5 composite helpers; the three version-guarded writes always re-read the parent immediately before the write), `__init__.py` (barrel).

**Stage 2 — `test_suite/`**: `conftest.py` plus 11 test modules.

## Test counts

| | tests | instances covered |
|---|---|---|
| Queue A (difficulty, §1.8) | 56 | 21 / 21, all >=2 tests |
| Queue B (corner, §1.9) | 91 | 67 / 67 non-stub, all >=1 test |
| **Total** | **147 functions -> 173 collected cases** | |

All 23 `excluded_because:` stubs were left untranslated; their `difficulty_instance` cross-references all resolve.

## Instances skipped
None. Two *cases within* instances were dropped as not PRD-determinate rather than weakened:
- `Corner/errors/support_statement_supersession_and_duplicate_guards_use_different_keys` — the `ERR_DUPLICATE_SUPPORT_STATEMENT` half: the PRD keys supersession on four fields where the design keys on three, so a same-key create is not uniquely derivable as 201-with-supersession vs 409.
- `Corner/errors/project_closure_guards_open_grants_then_open_incidents` — the *ordering* claim: the PRD states both closure gates but never fixes which wins when both are violated, so each gate is asserted independently.

## Audits
1. **Coverage** — pass (table above).
2. **PRD-citation pass** — all 147 citations verified as character-for-character (whitespace-normalised) substrings of `workspace/PRD.md`; no curly quotes, no fragments under 20 chars.
3. **Design-citation pass** — exactly one `Design:` line per test, always the last docstring line, every tag resolving to a real non-stub instance in the correct queue/section. No `skip`/`skipif`/`xfail`/mocking anywhere; no `validate_error_is_one_of` fallbacks. `pytest --collect-only` collects 173 cases with zero errors. No scaffold/yaml/design references anywhere in generated code outside the `Design:` lines.

## Design-index defects found (PRD won in every case)
- `Corner/validations/duplicate_cycle_blocks_a_draft_but_supersedes_a_submitted_disclosure` expects a DRAFT incumbent to yield 409; PRD §3.3 explicitly supersedes DRAFT/SUBMITTED/UNDER_REVIEW/RETURNED_FOR_REVISION and refuses only on CERTIFIED/REJECTED. Test asserts the PRD behaviour.
- `Difficulty/resource_temporal_overlap/area_windows_are_half_open_so_adjacent_grants_coexist` sequences setup so a `REQUESTED` straddling grant already occupies capacity when the trigger activates, contradicting its own "200" expectation; setup was reordered so the PRD's stated outcomes hold.
- Several instances assert scores/effort for `DECLARED` items, which §3.3 excludes from the scoring set (only `VERIFIED` items score) — affected tests assert the item's own `item_risk_points`, or add the PRD-declared verification/certification step so the value is genuinely observable.
- Multiple `*_at` literals asserted after transitions where the PRD stamps nothing (e.g. `terminated_at` outside `EXECUTED -> TERMINATED`) were dropped, as were exact clock-stamp literals for fields whose fractional-digit rendering the PRD does not fix (§2.5 fixes it only for `created_at`/`updated_at`).
- `Difficulty/boundary_precision_check/training_expiry_inclusive_at_the_due_instant` expects `training_compliant == true` pre-deadline, but an `ASSIGNED` institution-wide assignment already makes it false; only the EXPIRED-side claim is asserted.
- `Corner/state_machines/restore_that_no_longer_fits_capacity_is_revoked` expects `peak_concurrency_at_request == 1` where §3.7 computes it at request time (= 2); that assertion was omitted.

## Step 6: Generate implementation — 2026-09-02T07:17:25.655Z

Implementation complete and smoke-verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2371_research_security_foreign_influence_disclosure/workspace/implementation/`:

**Top level:** `start.sh`, `requirements.txt` (just `flask`), `app.py`, `db.py`, `util.py`, `errors.py`, `response.py`, `middleware.py`, `validate.py`

**`services/`** (domain logic, no HTTP): `enums.py` (all member sets + every scoring constant), `derive.py` (pure derivations: ownership chain/effective designation, completeness, item risk, risk score, posture, activation blockers, half-open capacity sweep, closed-interval travel overlap, device tier, severity freeze), `cascade.py` (recompute hops + grant/project/subaward fan-outs with §2.5 version bookkeeping), `screening.py` (both screening variants), `reconcile.py` (both reconciliation variants), `present.py` (12 explicit serializers, derived fields refreshed on read)

**`routes/`** (one blueprint per slice): `common.py`, `investigators.py`, `organizations.py`, `projects.py`, `personnel.py`, `disclosures.py`, `items.py`, `statements.py`, `travel.py`, `grants.py`, `incidents.py`, `training.py`, `subawards.py`, `clock.py`

## Endpoints

**56 declared endpoints** registered (58 URL rules total = 56 + `/_health` + Flask's `/static`), matching the SCAFFOLD/PRD endpoint table exactly, including `/_clock/set_current_utc`.

## Launcher

`start.sh` is `#!/usr/bin/env bash` + `set -euo pipefail`, `cd "$(dirname "$0")"`, a *guarded* flask install (only when the import fails — an unconditional pip install per reboot causes boot contention under `--isolation per-test-server`), then `exec python3 app.py`. `app.py` binds `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True, use_reloader=False)` — honors `$PORT`, binds 0.0.0.0, runs in the foreground via `exec` (no backgrounding, no reloader double-process).

## Storage

Process-local Python dicts in `db.py` keyed by bare UUID; twelve stores, all starting empty. No SQLite, no files, no seeding — verified with a fresh-boot assertion that `GET /investigators` returns `total_count == 0`. Logical clock starts at exactly `2026-08-01T00:00:00Z`; `created_at`/`updated_at` use wall clock with 3 fractional digits. Every request runs under a re-entrant store lock with per-request `touch` dedup so a record's `version` bumps at most once per request.

## Verification

Byte-compiled clean, then four scripted end-to-end smoke runs against live servers (~75 assertions, all passing on the spec-correct paths): envelope/meta shape, 401/403/404/400/409/412/422 catalog codes, pagination bounds, OCC on all three expected-version endpoints, disclosure review->plan->certify chain (item risk 95 = 30x3.0+5, risk 40 after the 20-point plan credit, `outside_effort_pct` 7.69, `total_commitment_pct` 132.69), both reconciliation variants on identical data (STRICT_AGENCY 3.00/CONSISTENT vs INSTITUTIONAL_ROLLUP 4.00/variance 1.00/omission 1/MATERIAL_DISCREPANCY), DIRECT_MATCH vs OWNERSHIP_TRANSITIVE divergence, the full designation cascade (descendant re-resolution -> subaward `BLOCKED` at 60 points -> project `SUSPENDED`/`SUBAWARD_BLOCKED` -> grants `SUSPENDED`/`PROJECT_SUSPENDED` -> count/posture), conditional restore (both the `ACTIVE` and the `CAPACITY_UNAVAILABLE` outcome, and `OFFICER_ACTION` grants correctly *not* restored), half-open capacity vs closed-interval travel touch semantics, incident severity freeze (15+15+10 = 40 -> `HIGH`, due +10 days), the four-hop substantiation cascade, SoD on notify, `ERR_AGENCY_NOTIFICATION_REQUIRED`, award close side effects (subawards terminated, personnel removed, effort conserved back to 0.00), and clock-driven training status re-evaluation.

Ambiguities resolved as noted earlier (e.g. posture gate before subaward screening on clearance; training gates accept `COMPLETED` or `WAIVED`; `REQUESTED -> REVOKED` leaves `revoked_at` null; officer-initiated `REQUESTED -> SUSPENDED` is accepted with `status_reason` `OFFICER_ACTION` rather than refused, since the transition is declared). `/_clock/set_current_utc` returns `{"current_utc": ...}` in an object envelope, as the spec declares no output body.

## Step 7: Run tests and iterate — 2026-09-02T11:45:00.000Z

Sweep complete and clean on the first iteration.

**Iterations run: 1** (one full 8-round parallel sweep, launched under `setsid nohup`, all rounds joined with `wait`, no early exit).

**Result: all 8 rounds passed == total.**

| round | passed | failed | errors | skipped | total |
|---|---|---|---|---|---|
| 1–8 (each) | 173 | 0 | 0 | 0 | 173 |

Sweep duration ~1707s per round under heavy host contention (other pipelines, e.g. task_2396, were sweeping concurrently on the same box).

**Tests deleted:** none — no test failed in any round, so STEP 1 (PRD coverage / unique-derivability) was never triggered.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

**Verification checks performed beyond the pass counts:**
- `results.*.json` structure confirms 173 real test records per round with `skipped: 0`, `errors: 0` — no silent collection loss (147 test functions → 173 parametrized cases, matching the artifact's documented count).
- No `pytest.mark.skip` / `xfail` / mocking anywhere in `test_suite/` or `test_helpers/` (the only `skip` hits are prose in a test name/docstring about "cannot skip agency notification").
- No reaping artifact: `grep -c Terminated` on `workspace/sweep.log` → 0, and rounds finished at staggered times, so the pass results are genuine rather than a masked SIGTERM pattern.
- Cardinal-rule audit of `workspace/implementation/`: no `sqlite`, no `open(`, no `json.dump`, no `/tmp`, no `pickle`/`shelve` anywhere — storage is in-memory Python dicts only, so per-test-server isolation truly wipes state; no startup seeding.

Orchestrator re-verified all 8 `results.*.json` files independently: 173/173 passed, 0 failed/errors/skipped in every round.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T11:46:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 iterations beyond baseline — 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. `PRD.md` therefore already determined every behavior the tests exercised, there is no `<step_7_diff>` to hand off, and no PRD_FINALIZED.md is produced. Step 9 will start from `workspace/PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T12:12:00.000Z

`PRD_COMPLETED.md` is written. Every change is an in-paragraph insert or revision; no new sections, no new paragraphs, no new bullets — the file has the same 464 lines as the source, with 46 lines touched.

## Counts

- **Source** `workspace/PRD.md` — 464 lines, 117,439 chars
- **Output** `workspace/PRD_COMPLETED.md` — 464 lines, 132,528 chars (**char delta +14,978**)
- **Ambiguity-pins (PRD silent):** 43
- **Mismatch-revisions (PRD said something else):** 8

## Changes

Mismatch-revisions:

- §3.6 subaward decisions — revise — mismatch — every termination path stamps `terminated_at`, not only termination out of `EXECUTED` — `services/cascade.py:167-171`, `routes/subawards.py:152-155`
- §3.5 statement create — revise — mismatch — `ERR_DUPLICATE_SUPPORT_STATEMENT` is never returned; both admitted callers may supersede — `routes/statements.py:55-67`
- §3.7 grant oscillation — revise — mismatch — `REQUESTED → SUSPENDED` is also officer-requestable, recording `OFFICER_ACTION` — `routes/grants.py:17`, `165-168`
- §3.1 designation cascade — revise — mismatch — re-screened subawards transition only where the re-screen actually yields `BLOCKED`; an unscreened subaward is skipped — `services/cascade.py:189-206`
- §3.6 initial clearance — revise — mismatch — posture gate is checked *before* the subaward-screening gate — `routes/projects.py:184-201`
- §3.6 re-clearance — revise — mismatch — same posture-before-screening order, incidents last — `routes/projects.py:184-201`
- §2.8 + grant activation — revise — mismatch — gate order is `ERR_PROJECT_NOT_CLEARED` → `ERR_PERSONNEL_NOT_ACTIVE` → posture → training → capacity — `routes/grants.py:124-155`
- §3.7 grant activation — revise — mismatch — activation *overwrites* `peak_concurrency_at_request` rather than leaving the request-time value — `routes/grants.py:157-158`

Ambiguity-pins (grouped by section):

- §2.1 — insert — headers trimmed; whitespace-only is `ERR_UNAUTHENTICATED` — `middleware.py:18-23`
- §2.2 — insert x3 — `api_request_id` shape (`req_` + 20 uppercase/digits); `total_count`/`has_more` semantics; effort values serialise as JSON numbers, cents/scores as integers — `response.py:12-20,44-49`, `util.py:93-99`
- §2.3 — insert x2 — non-integer `limit`/`offset` and negative `offset` are 400; out-of-set filters are 400 while blank filters are ignored; `created_at` ties break on insertion sequence — `validate.py:189-231`, `db.py:79-83`
- §2.4 — insert — `current_utc` stored and echoed verbatim; the 13 clock-stamped fields carry that exact string — `routes/clock.py:16-19`
- §2.5 — insert x3 — `created_at`/`updated_at` come from real wall time; `version` advances at most once per request; reads refresh derived fields without bumping `version` — `db.py:31-46`, `services/present.py:1-13`
- §2.7 — revise — the expected-version field must be a present JSON integer (400 at step 6, before comparison) — `routes/disclosures.py:44-48`
- §2.8 — insert x4 — missing/non-string mandatory body FK yields the 404, not 400; placement of all non-numbered checks; conditionally-required fields at step 6 plus JSON-number/null/instant/empty-body rules; SDN gate precedes the `mitigation_justification` check — `routes/common.py:38-45`, `validate.py:14-18,120-160`, `routes/subawards.py:130-137`
- §2.10 — insert — an unresolvable `parent_organization_id` ends the walk quietly — `services/derive.py:35-37`
- §3.1 — insert x4 — `email` is any non-empty string, compared case-sensitively; `designated_on` mandatory when designation != `NONE` and forced null otherwise; subsidiaries list ignores stake size; ownership write needs both keys and rolls back on cycle/depth — `routes/investigators.py:24-36`, `routes/organizations.py:19-25,139-160`, `services/derive.py:76-78`
- §3.2 — insert x2 — `to_status` enum-vs-undeclared split (400 vs 409); a null `plan_effort_cap_pct` imposes no ceiling — `routes/projects.py:111-115`, `routes/personnel.py:100-106`
- §3.3 — insert — item role-per-transition is `ERR_UNAUTHORIZED` after the transition check; owner check before `to_status` — `routes/items.py:56-73`
- §3.4 — insert x5 — review action order (transition before reviewer guard) and `review_note` discarded; `REQUIRE_PLAN` needs `plan_status == NOT_REQUIRED`; plan endpoint per-action role `ERR_UNAUTHORIZED`, `ISSUE` field-shape-first ordering and empty `plan_required_actions`; `ACKNOWLEDGE` role+owner ahead of the state check; `WAIVE` ignores the risk trigger — `routes/disclosures.py:163-236,280-352`
- §3.5 — insert — newest-certified tie-break falls through to insertion sequence, null `submitted_at` sorts first — `services/reconcile.py:21-30`
- §3.6 — insert x2 — screening admissible only from `PENDING`; security `TERMINATED` leaves `security_status_reason` unchanged and stamps subaward `terminated_at` — `routes/subawards.py:98-100`, `routes/projects.py:215-221`
- §3.7 — insert x6 — travel role-per-transition `ERR_UNAUTHORIZED`; approval reads the stored tier without re-projecting; officer restore also runs the training gate but not the roster check and does not re-stamp `activated_at`; cascaded restore checks capacity only and leaves `peak_concurrency_at_request` alone; cascaded capacity revocation stamps `revoked_at`; `REQUESTED -> REVOKED` leaves `revoked_at` null — `routes/travel.py:16-24,112-126,142-163`, `routes/grants.py:157-181`, `services/cascade.py:64-71,131-141`
- §3.8 — insert x2 — lead-presence shape check precedes the transition check (and is ignored on other transitions); `notification_due_on` is a full instant, not a bare date — `routes/incidents.py:121-131`, `services/derive.py:555-557`
- §3.9 — insert x3 — training complete/waive perform no ownership check; award closure and withdrawal remove personnel without revoking grants and stamp subaward `terminated_at` — `routes/training.py:83-101`, `routes/projects.py:159-167`
- §4 — insert — unknown route/method answer `ERR_INVALID_REQUEST` at 404/405 rather than 400; trailing slashes are equivalent — `app.py:38,64-74`

Orchestrator verification: `PRD_COMPLETED.md` present, 464 lines / 132,528 chars, 92 changed lines in the unified diff vs `PRD.md`, file ends cleanly (no mid-section truncation). Pipeline complete.
