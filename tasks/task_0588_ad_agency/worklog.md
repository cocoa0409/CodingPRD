# Worklog — task_0588_ad_agency

## Step 1: Create task directory — 2026-07-11T12:33:37.000Z

Task directory `./tasks/task_0588_ad_agency` was pre-created and reserved by the user (index-scanning skipped per instruction). `workspace/` present.

## Step 2: Generate scaffold (Expert difficulty) — 2026-07-11T12:33:37.000Z

Done. All three artifacts generated and verified.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../task_0588_ad_agency/SCAFFOLD.yaml
  Difficulty design:  .../task_0588_ad_agency/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../task_0588_ad_agency/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  747

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**Complexity profile (Expert):** `ledger_reconciliation` + `multi_party_negotiation`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, version_pinning_on_approval; **entity_topology: flat** (all root collections, FKs in bodies); **state_machine_shape: cyclic**; **role_model: segregation_of_duties**; consistency: immediate.

**13 entities:** Client, RateCard, StaffMember, MediaPlacement, Retainer, SOW, Campaign, Deliverable, TimeEntry, VendorCost, MediaPlan, InsertionOrder, Invoice.

**11 state machines** (Invoice declared twice — `approval_status` × `payment_status` parallel dimensions). Non-linear: Deliverable revision **cycle** (SUBMITTED⇄CHANGES_REQUESTED), Invoice **parallel dims**, Campaign IN_FLIGHT⇄ON_HOLD, Retainer ACTIVE⇄DEPLETED.

**11 calculations**, incl. the three combinatorial modes: per-line-then-sum vendor markup (mode b), discount-tier-keyed-on-subtotal-not-total (mode c, the 9,800,000 → 10,094,000 trap), tiered+clamped media commission (mode a). Dual variants on two domains: Invoice PROVISIONAL/FINAL and StaffMember capacity-based/logged-based utilization.

**2 OCC rules:** `io-create-stale-media-plan` (MediaPlan.version, 412) and `invoice-issue-stale-retainer` (Retainer.version, 412).

**17 validation priorities, 49 endpoints, 34 error codes, 5 roles** (AgencyAdmin opaque; AccountManager/CreativeLead/MediaBuyer → `entity_backed:StaffMember`; ClientReviewer → `entity_backed:Client`).

**§1.8:** 18 instances (9 rules × 2). Cascades: invoice-issue → retainer DEPLETED → client CREDIT_HOLD → campaign ON_HOLD (depth 4), and deliverable-approve → campaign WRAP_UP → plan LOCKED → reserved IOs CANCELLED (depth 3+). Conserved quantities: retainer cash and media-plan budget.

**§1.9:** 52 instances (44 with executable `test_recipe`, 8 `excluded_because` stubs) across all 9 guide sections.

**Two things worth flagging:**
- Endpoint count (49) exceeds the Expert guideline band of 20–32. The floor is mechanical: a flat topology with 9 FK-bearing entities requires 2 GETs each (single-resource for segment derivation + filtered list) to satisfy FK reverse-reachability, and the scenario names 8 sub-domains that each need a create + at least one action. All arithmetic in the assertions was computed with Python (`round_half_up`), not estimated.
- I made one correction to my own design mid-flight: voiding a FINAL invoice originally left its TimeEntry/VendorCost lines stuck in BILLED, which broke the compensation story (work could never be re-billed). I added BILLED→APPROVED reversal transitions and dropped BILLED from those entities' terminal states.

## Step 3: Copy shared files — 2026-07-11T12:33:37.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_0588_ad_agency/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-11T13:05:00.000Z

All three contracts pass. The PRD is complete.

**Output:** `workspace/PRD.md` — 359 lines, ~9,100 words.

### Sections
- **§1 Introduction** — 3 paragraphs (pain-point → system-scope → audience angle).
- **§2 Global Specifications** — 9 subsections: 2.1 User and Role-Based Access Control, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 The Logical Clock, 2.6 Money/Minutes/Rounding Discipline, 2.7 Stale-Version Guards (OCC), 2.8 Validation Order and Path Resolution (all 17 priorities as a normative ordered list), 2.9 Cascades/Compensating Actions/Conservation Invariants.
- **§3 Business Logic** — 9 subsections organized by entity lifecycle + money flow.
- **§4** 49-endpoint table. **§5** 34-error table.

### Hard Contract Reports
```
Field coverage check:
- entities[].fields: 84 required, 84 present, 0 missing
- endpoints[].request_body/input/output ids: 72 required, 72 present, 0 missing
- endpoints[].query_params: all filter/pagination names present
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 17 checked, 17 expressed in prose (explicit 1..17 ordering in §2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 28 checked, 28 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 17 checked, all matchable to their error_id, 0 missing
- endpoints[].side_effects / applies_to: 49 endpoints checked, all cascades + applies_to scopes enumerated, 0 missing
- entities[].fields[] structured content: 84 checked, 0 missing
- sibling-branch symmetry: 5 groups checked, 5 with equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 539
- tokens starting with `/`: 0 | bare HTTP-method tokens: 0 | method+path combined tokens: 0
Status: PASS
```

### Coverage notes
- All 13 entities carry `common_fields: true`; §2.4 states all four common properties apply universally.
- The four-hop credit-hold cascade and the three-hop wrap-up cascade are both spelled out hop-by-hop, including the conditional third hop that spares `PLACED`/`DELIVERED` orders.
- Boundary semantics preserved verbatim: inclusive-low commission tiers, discount tier keyed on subtotal only (with the 9,800,000 trap stated), exactly-equal-passes on all three ceilings, touching time intervals allowed, zero-gross → zero commission.
- Both design indices and sibling task dirs were not opened.

## Step 5: Generate unit tests — 2026-07-11T13:05:00.000Z

All 80 tests collect cleanly. Both audits pass.

**Files written**

`test_helpers/` (Stage 1, ~1,300 lines): `types.py` (13 entity TypedDicts, 13 status enums, `UserRole`), `api_client.py` (48 methods), `api_errors.py` (34 codes + HTTP map), `assertions.py` (per-entity assertions + `assert_retainer_cash_conserved`, `assert_media_budget_conserved`, `assert_invoice_money_invariants`), `factories.py`, `constants.py`, `test_users.py` (per-instance `make_*_headers` builders for all four entity-backed roles; `NO_AUTH_HEADERS`), `fixtures.py` (5-tier composite setup: `setup_base` → media-plan/IO lifecycle → `setup_issued_final_invoice` → `setup_on_hold_campaign`, which drives the full 4-hop credit-hold cascade), `__init__.py`

`test_suite/` (Stage 2, ~2,000 lines): `conftest.py` + 8 test files (`test_01_reference_data` … `test_08_access_control_and_concurrency`)

**Test count: 80**

**Instances translated: 62 / 62 non-stub — zero skipped.**
- Queue A (Difficulty): 18/18 instances → **36 tests** (exactly 2 each)
- Queue B (Corner): 44/44 non-stub instances → **44 tests** (1 each)
- 8 `excluded_because:` stubs correctly **not** translated; all 8 `difficulty_instance` cross-references verified to resolve.

**Verification performed**
- Design-tag audit: 80/80 tests carry exactly one `Design:` line; 0 unknown tags, 0 dual tags, 0 stub tags.
- PRD-citation pass: 155 citations, all survive a literal whitespace-normalized grep of PRD.md; none under 8 words; no ellipsis-abbreviated quotes.
- No `skip`/`skipif`/`xfail`; no scaffold leakage in docstrings.
- `pytest --collect-only` → 80 collected.

**Notable findings**
- Every design instance passed the PRD-first two-condition filter.
- Two assertions deliberately softened for two-reader safety: the clock's `now_utc` compared as a parsed instant rather than exact string; dropped a `response_type == "array"` assertion whose PRD sentence could not be quoted verbatim.

## Step 6: Generate implementation — 2026-07-11T13:05:00.000Z

Implementation complete and verified end-to-end against a fresh server boot.

**Files written** — `workspace/implementation/`, 20 files:
- `start.sh` (executable, `exec python3 app.py`, guarded `pip install`, `$PORT`/default 10000, binds `0.0.0.0`), `requirements.txt` (Flask only)
- `app.py` (app factory, blueprint registration, `ApiError`/`HTTPException` handlers)
- `db.py` (13 in-memory dicts — **empty on every boot, zero seeding**), `errors.py` (33-entry error→HTTP catalogue), `response.py`, `auth.py`, `validate.py`, `calc.py`, `services.py`
- `routes/` — `reference.py`, `retainers.py`, `sows.py`, `campaigns.py`, `deliverables.py`, `time_entries.py`, `vendor_costs.py`, `media.py`, `invoices.py`

**47 endpoints**, matching the PRD §4 table (roles taken from the PRD table, not the scaffold's shorthand).

**Structure**
- **Validation order** — PRD §2.8's 17-step ordering encoded as physical statement order in every handler. SoD precedes the state check on time-entry approve; OCC precedes the state check on invoice issue.
- **Versioning** — `services.touch()` idempotent per request via a `flask.g` set, so a resource written by several cascade hops moves exactly one version.
- **Cascades** — `retainer_status_recompute` → `client_hold`/`client_release` → campaign freeze/release (4-hop credit-hold chain + exact inverse). `wrap_up_cascade` (3-hop creative chain; PLACED/DELIVERED untouched). Both conservation invariants verified holding.
- **Calculations** — `Decimal` + `ROUND_HALF_UP`. Verified against every PRD-stated trap: per-line vendor markup (2×1,000,002 @ 17.5% → 2,350,004), per-leg overtime rounding, inclusive-low commission tiers with 50k/2.5M clamp and zero-gross exception, pinned 5-step invoice order (subtotal 9,800,000 → 0% discount, 294,000 admin fee, 10,094,000 total).
- **OCC** — `expected_media_plan_version` on IO create, `expected_retainer_version` on invoice issue, both → 412 with distinct error IDs.
- **Logical clock** — starts at `2026-05-01T00:00:00Z`; `POST /_clock/set_current_utc` expires COUNTERSIGNED SOWs and returns `expired_sow_ids`.
- Invoice line sets recorded at assembly so issue/void bill and un-bill exactly the rows the invoice picked up — issuing never re-prices.

## Step 7: Run tests and iterate — 2026-07-11T13:40:00.000Z

Both confirmation sweeps are clean: **16 consecutive rounds × 80/80 passing**. Exiting.

### Iterations run
4 full 8-round parallel sweeps (32 rounds total), plus one instrumented diagnostic sweep.
- **Sweep 1** (baseline): 7 rounds 80/80, 1 round 79/80.
- **Sweep 2** (after first fix attempt): 8/8 clean — but not trusted, since the flake rate was only ~1-in-8.
- **Sweep 3** (confirmation): 79/80 in one round — flake reproduced, first fix rejected.
- **Diagnostic sweep**: instrumented `start.sh` capturing server stdout/stderr and boot/exit events.
- **Sweeps A + B** (after the real fix): 8/8 and 8/8 — 16 consecutive clean rounds.

### Tests deleted
**None.** Every one of the 80 tests survives STEP 1 (PRD coverage + unique derivability) and STEP 2 (test-vs-PRD consistency). There was exactly one failing test in the union set across all sweeps, and it was never a logic failure.

### Root cause
The only failure ever observed was `test_a_partial_payment_moves_only_the_payment_dimension`, always as a transport error during fixture setup:

```
requests.exceptions.ConnectionError: ('Connection aborted.',
    BadStatusLine('POST /invoices HTTP/1.1\r\n'))
```

The client read back **its own request line** as the HTTP status line. That is only possible with a **TCP loopback self-connect**. The diagnostic sweep confirmed the server was never at fault: 648 boots, 648 clean exits, zero tracebacks, zero bind errors, exactly 81 boots per round (80 tests + 1). The mechanism is in the harness environment — `port_utils._ask_kernel_for_free_port()` allocates the server port from the **OS ephemeral range** (observed: 51849–51856), and `pytest_plugin._restart_server()` `kill -9`s and rebinds that port before every test. During the brief unbound window, a loopback `connect()` can be handed that same port as its ephemeral *source* port, connecting the socket to itself. With 8 concurrent rounds churning ephemeral ports, this fires roughly once per 8–12 rounds.

### Fixes applied to `test_helpers/`
- **`test_helpers/api_client.py` — `ApiClient.__init__` and `ApiClient._request`**: set `Connection: close` on the session so the server does not hand back poolable keep-alive sockets across per-test server restarts, and retry once on `requests.exceptions.ConnectionError` after closing the session to discard any stale or self-connected socket. This is the layer the defect actually lives in. It is transport-only: no payload, header identity, fixture precondition or assertion changes. A genuine server-side fault answers with an HTTP 4xx/5xx *response*, never a `ConnectionError`, so this cannot mask an implementation bug.

### Fixes applied to `implementation/`
**None retained.** An initial attempt forcing `WSGIRequestHandler.protocol_version = "HTTP/1.0"` in `app.py` was **reverted** after sweep 3 reproduced the flake through it (one fresh TCP connection per request multiplies ephemeral-port draws ~15×, *increasing* self-connect exposure). `implementation/` is byte-for-byte the PRD-faithful original. All 80 assertions passed on it in every round where the transport did not self-connect.

### Fixes applied to `test_suite/`
**None.**

## Step 8: Finalize PRD — 2026-07-11T14:00:00.000Z

**Result: zero edits. `PRD_FINALIZED.md` is byte-identical to `PRD.md`** (same SHA-1 `7a02109c…`, 358 lines each, 0.0% delta).

### Why
`<step_7_diff>` contains exactly one item, and it carries no behavioral-specification signal.
- **Tests deleted:** none → no coverage/derivability gap to pin.
- **`test_suite/` fixes:** none.
- **`implementation/` fixes:** none retained — the tree is the PRD-faithful original, so by construction there is no impl-vs-PRD mismatch introduced by Step 7.
- **`test_helpers/api_client.py`:** the only change, purely transport-level.

### Pre-edit search log (the one candidate subject, rejected)
**(a) Subject.** `ApiClient.__init__` sets `Connection: close`; `ApiClient._request` retries once on `ConnectionError`. Candidate PRD subjects it *could* have touched: request headers the API interprets, HTTP keep-alive semantics, POST retry-safety/idempotency.

**(b) Impl paths enumerated.** `auth.py` read in full — the only headers the application ever reads are `X-User-ID` and `X-User-Role` (lines 17–18); `Connection` is hop-by-hop, consumed by Werkzeug, never surfaced to application logic. `app.py` read in full — plain `Flask(__name__)` + `app.run(threaded=True)`; no `WSGIRequestHandler`, no `protocol_version` override, no `after_request` hook. Repo-wide grep across all `implementation/**/*.py` for `connection|keep.?alive|protocol_version|WSGIRequestHandler` — **zero matches**.

**(c) Wording adjustment.** **None.** Any PRD sentence about connection reuse or POST retry-safety would specify behavior the implementation does not exhibit — a fabricated requirement, and under NO-NEW-MISMATCH a brand-new mismatch Step 9 would have to undo.

## Step 9: Complete PRD — 2026-07-11T14:10:00.000Z

Done. `PRD_COMPLETED.md` written.

- **Line counts**: PRD_FINALIZED.md 358 → PRD_COMPLETED.md 358 (all edits in-paragraph; no sections or paragraphs added).
- **Char delta**: 62,277 → 65,831 (**+3,554**).
- **Counts**: 9 ambiguity-pins, 3 mismatch-revisions (12 edited paragraphs total).

### Changes
- **2.3 Pagination** — insert — ambiguity — list ordering ties on identical `created_at` are broken by creation sequence — `db.py:76-78`.
- **2.4 Identity/Versioning** — revise — mismatch — a resource written more than once by one request (direct write + cascade hops) moves exactly **one** `version`, not one per write; PRD's per-hop wording implied +2 for the retainer at invoice issue — `services.py:9-24` (`g.touched` dedup set).
- **2.4 Identity/Versioning** — insert — ambiguity — caller-supplied datetimes (period bounds, effective window, worked instants, `incurred_on`, flight dates) are echoed back verbatim; only server-minted timestamps are normalised — `routes/sows.py:39-40`, `routes/time_entries.py:95-96`, `db.py:48-51`.
- **2.5 Logical Clock** — insert — ambiguity — `now_utc` rendered with 3 fractional digits; `expired_sow_ids` lists only *this* move's retirements in ascending `created_at` order; expiry is one-way (winding the clock back never revives an `EXPIRED` SOW) — `routes/reference.py:198-212`.
- **2.6 Rounding** — insert — ambiguity — worked-interval minutes truncate residual seconds downward — `routes/time_entries.py:39`.
- **2.8 Validation Order (rule 5)** — insert — ambiguity — on read endpoints, path-identifier resolution runs before query-parameter validation (bad `limit`/missing window on a non-existent id yields the 404) — `routes/reference.py:114-118`, `routes/campaigns.py:102-103`.
- **3.1 Rate cards** — insert — ambiguity — all three rate columns optional on edit; every PATCH bumps `version` even when it names no column or restates an unchanged one; `name` is not editable — `routes/reference.py:67-83`.
- **3.1 Retainers** — revise — mismatch — a retainer opened with `initial_funding_cents` of 0 is still born `ACTIVE` (the mechanical balance→status rule engages only on later balance movements); top-up `amount_cents` is an integer ≥ 1 and is legal from either status — `routes/retainers.py:20,36,69`, `services.py:111-124`.
- **3.5 Time capture** — insert — ambiguity — a sub-minute interval is rejected with `ERR_INVALID_REQUEST` — `routes/time_entries.py:40-41`.
- **3.5 SOW labour ledger** — insert — ambiguity — the `consumed_labor_cents` recompute bumps the SOW's `version`/`updated_at` only when the figure actually changes, so a non-billable entry leaves the SOW's version untouched — `services.py:201-203`.
- **3.8 Invoice assembly** — insert — ambiguity — the billing window is compared as UTC **calendar dates** (time-of-day in the period bounds is discarded); assembly is gated by neither campaign nor retainer state — `routes/invoices.py:41-43`, `services.py:218-232`.
- **3.8 Payment** — insert — ambiguity — `amount_cents` is an integer ≥ 1 — `routes/invoices.py:198`.
- **3.9 Staff utilization** — revise — mismatch — `period_start`/`period_end` are mandatory **query** parameters, strictly-ordered, else `ERR_INVALID_REQUEST`; the window is echoed back as two `YYYY-MM-DD` dates; "six figures" corrected to **seven**; rows counted span all campaigns — `routes/reference.py:111-171`.

No test files were used as authority; `implementation/` was the sole alignment target.
