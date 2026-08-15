from flask import Blueprint


def make_blueprint(name):
    # api_prefix is "/" — all endpoints mount at the service root.
    return Blueprint(name, __name__)
