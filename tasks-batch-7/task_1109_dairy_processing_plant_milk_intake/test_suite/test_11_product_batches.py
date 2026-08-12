"""Product batch coding: product-specific shelf-life caps."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_batch,
    setup_running_run,
    validate_error,
)

OP = TEST_USERS["pasteurizer_operator_headers"]


def test_code_batch_shelf_life_cap_exceeded(api):
    """PRD §3.6: "Coding enforces the product-specific shelf-life cap — at most
    21 days for `WHOLE_MILK`, `TWO_PERCENT`, and `SKIM`; at most 30 days for
    `HEAVY_CREAM`; at most 180 days for `BUTTER`; and at most 270 days for
    `CONDENSED_SKIM` — otherwise `ERR_SHELF_LIFE_EXCEEDED`."

    Design: Corner/errors/err_shelf_life_exceeded
    """
    run = setup_running_run()
    batch = make_batch(run["id"], product_code="WHOLE_MILK", shelf_life_days=30)
    get_success_data(api.begin_batch(run["id"], batch["id"], {}, OP))

    res = api.code_batch(run["id"], batch["id"], {}, OP)
    validate_error(res, ApiErrorId.ERR_SHELF_LIFE_EXCEEDED)
