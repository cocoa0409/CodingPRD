import os

from flask import Flask

from db import db
from errors import ApiError
from response import error_response

app = Flask(__name__, static_folder=None)
app.config['JSON_SORT_KEYS'] = False


@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response('ERR_NOT_FOUND', 404, 'resource not found')


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response('ERR_NOT_FOUND', 404, 'resource not found')


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_response('ERR_INTERNAL', 500, str(e))


from routes import core, orders, estimates, assignments, transit, crews, settlement

for mod in (core, orders, estimates, assignments, transit, crews, settlement):
    app.register_blueprint(mod.bp)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), threaded=True)
